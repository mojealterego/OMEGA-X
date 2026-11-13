"""Offline authenticated tenant-scoped JSON bridge; no network and no remote actions."""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
from .adapter import encode, decode, _reject_duplicates

_TENANT = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
_NONCE = re.compile(r'^[a-f0-9]{32}$')
_DOMAIN = b'OMEGA-X-ENVELOPE-V2\0'
_MAX_TTL_NS = 86_400_000_000_000
_MAX_SIZE = 3_000_000


class AuthenticationError(ValueError):
    """Signature, TTL, schema or replay authentication failure."""


def _validate(tenant, request_id, key, nonce, issued_ns, ttl_ns):
    if not isinstance(tenant, str) or not _TENANT.fullmatch(tenant):
        raise ValueError('invalid tenant')
    if not isinstance(request_id, str) or not request_id.isascii() or not 0 < len(request_id) <= 128:
        raise ValueError('invalid request id')
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError('HMAC key must have at least 256 bits')
    if not isinstance(nonce, str) or not _NONCE.fullmatch(nonce):
        raise ValueError('nonce must be 128-bit lowercase hex')
    if type(issued_ns) is not int or not 0 <= issued_ns < 2**63:
        raise ValueError('invalid issuance time')
    if type(ttl_ns) is not int or not 0 < ttl_ns <= _MAX_TTL_NS or issued_ns + ttl_ns >= 2**63:
        raise ValueError('invalid TTL')


def _canonical(body: dict) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def sign_request(tasks, request_id: str, tenant: str, key: bytes, issued_ns: int,
                 ttl_ns: int = 60_000_000_000, nonce: str | None = None) -> bytes:
    nonce = nonce if nonce is not None else secrets.token_hex(16)
    _validate(tenant, request_id, key, nonce, issued_ns, ttl_ns)
    payload = encode(tasks, request_id)
    body = {'schema_version': 2, 'tenant': tenant, 'request_id': request_id,
            'issued_ns': issued_ns, 'ttl_ns': ttl_ns, 'nonce': nonce,
            'payload_sha256': hashlib.sha256(payload).hexdigest(),
            'payload_b64': base64.b64encode(payload).decode('ascii')}
    body['signature'] = hmac.new(key, _DOMAIN + _canonical(body), hashlib.sha256).hexdigest()
    raw = _canonical(body)
    if len(raw) > _MAX_SIZE:
        raise ValueError('signed envelope exceeds limit')
    return raw


def verify_request(raw: bytes, key: bytes, now_ns: int):
    if not isinstance(raw, bytes) or len(raw) > _MAX_SIZE:
        raise AuthenticationError('invalid envelope size')
    if type(now_ns) is not int or not 0 <= now_ns < 2**63:
        raise ValueError('invalid verification time')
    try:
        body = json.loads(raw, object_pairs_hook=_reject_duplicates)
        expected = {'schema_version', 'tenant', 'request_id', 'issued_ns', 'ttl_ns', 'nonce',
                    'payload_sha256', 'payload_b64', 'signature'}
        if not isinstance(body, dict) or set(body) != expected or type(body['schema_version']) is not int or body['schema_version'] != 2:
            raise AuthenticationError('invalid v2 schema')
        _validate(body['tenant'], body['request_id'], key, body['nonce'], body['issued_ns'], body['ttl_ns'])
        if not body['issued_ns'] <= now_ns <= body['issued_ns'] + body['ttl_ns']:
            raise AuthenticationError('request expired or issued in future')
        sig = body.pop('signature')
        if not isinstance(sig, str) or not re.fullmatch(r'[0-9a-f]{64}', sig):
            raise AuthenticationError('invalid signature encoding')
        actual = hmac.new(key, _DOMAIN + _canonical(body), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, actual):
            raise AuthenticationError('invalid request authentication')
        payload = base64.b64decode(body['payload_b64'], validate=True)
        if not hmac.compare_digest(hashlib.sha256(payload).hexdigest(), body['payload_sha256']):
            raise AuthenticationError('payload digest mismatch')
        request_id, tasks = decode(payload)
        if request_id != body['request_id']:
            raise AuthenticationError('inner/outer request id mismatch')
        return body['tenant'], request_id, tasks, body['nonce']
    except (KeyError, TypeError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        if isinstance(exc, AuthenticationError):
            raise
        raise AuthenticationError('invalid authenticated envelope') from exc


class ReplayStore:
    def __init__(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, isolation_level=None, timeout=5)
        self._db.execute('PRAGMA journal_mode=WAL')
        self._db.execute('PRAGMA synchronous=FULL')
        self._db.execute('''CREATE TABLE IF NOT EXISTS nonce_claims (
            tenant TEXT NOT NULL, nonce TEXT NOT NULL, expires_ns INTEGER NOT NULL,
            PRIMARY KEY(tenant,nonce))''')

    def claim(self, tenant: str, nonce: str, expires_ns: int, now_ns: int) -> bool:
        if not _TENANT.fullmatch(tenant) or not _NONCE.fullmatch(nonce):
            raise ValueError('invalid tenant/nonce')
        if type(now_ns) is not int or type(expires_ns) is not int or not 0 <= now_ns < expires_ns < 2**63:
            raise ValueError('invalid nonce lifetime')
        self._db.execute('BEGIN IMMEDIATE')
        try:
            self._db.execute('DELETE FROM nonce_claims WHERE expires_ns <= ?', (now_ns,))
            cur = self._db.execute('INSERT OR IGNORE INTO nonce_claims VALUES (?,?,?)',
                                   (tenant, nonce, expires_ns))
            self._db.execute('COMMIT')
            return cur.rowcount == 1
        except BaseException:
            self._db.execute('ROLLBACK')
            raise

    def close(self):
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
