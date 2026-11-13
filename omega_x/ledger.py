"""SQLite WAL evidence ledger: idempotent transactions and tamper-evident SHA-256 chain."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sqlite3


class LedgerConflict(ValueError):
    """Idempotency key reused with conflicting payload or result."""


class LedgerCorrupt(ValueError):
    """Detected break in append-only evidence hash-chain."""


class EvidenceLedger:
    def __init__(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, isolation_level=None, timeout=5)
        self._db.execute('PRAGMA journal_mode=WAL')
        self._db.execute('PRAGMA synchronous=FULL')
        self._db.execute('PRAGMA busy_timeout=5000')
        self._db.execute('''CREATE TABLE IF NOT EXISTS evidence (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL UNIQUE,
            payload_sha256 TEXT NOT NULL,
            result_json TEXT NOT NULL,
            previous_hash TEXT NOT NULL,
            record_hash TEXT NOT NULL)''')

    @staticmethod
    def _hash(previous: str, request_id: str, payload_sha: str, result_json: str) -> str:
        raw = json.dumps([previous, request_id, payload_sha, result_json],
                         separators=(',', ':'), ensure_ascii=True).encode()
        return hashlib.sha256(raw).hexdigest()

    def append(self, request_id: str, payload: bytes, result: dict) -> int:
        if not isinstance(request_id, str) or not request_id.isascii() or not 0 < len(request_id) <= 128:
            raise ValueError('invalid request id')
        if not isinstance(payload, bytes) or len(payload) > 2_000_000:
            raise ValueError('invalid payload')
        if not isinstance(result, dict):
            raise ValueError('result must be a JSON object')
        serialized = json.dumps(result, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
        payload_hash = hashlib.sha256(payload).hexdigest()
        self._db.execute('BEGIN IMMEDIATE')
        try:
            old = self._db.execute('SELECT seq,payload_sha256,result_json FROM evidence WHERE request_id=?',
                                   (request_id,)).fetchone()
            if old:
                if old[1:] != (payload_hash, serialized):
                    raise LedgerConflict('idempotency key reused for different content')
                self._db.execute('COMMIT')
                return old[0]
            previous_row = self._db.execute('SELECT record_hash FROM evidence ORDER BY seq DESC LIMIT 1').fetchone()
            previous = previous_row[0] if previous_row else '0' * 64
            digest = self._hash(previous, request_id, payload_hash, serialized)
            cur = self._db.execute('INSERT INTO evidence(request_id,payload_sha256,result_json,previous_hash,record_hash) VALUES(?,?,?,?,?)',
                                   (request_id, payload_hash, serialized, previous, digest))
            seq = cur.lastrowid
            self._db.execute('COMMIT')
            return seq
        except BaseException:
            self._db.execute('ROLLBACK')
            raise

    def verify(self) -> dict:
        previous = '0' * 64
        count = 0
        for seq, req, payload, result, prev, record in self._db.execute(
            'SELECT seq,request_id,payload_sha256,result_json,previous_hash,record_hash FROM evidence ORDER BY seq'):
            count += 1
            if seq != count or previous != prev or record != self._hash(prev, req, payload, result):
                raise LedgerCorrupt(f'evidence chain invalid at seq {seq}')
            previous = record
        return {'records': count, 'head_sha256': previous, 'verified': True}

    def close(self):
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
