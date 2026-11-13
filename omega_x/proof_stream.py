"""Authenticated, bounded, append-only local evidence stream with external anchors.

Single-file fsync durability and Linux flock cross-process exclusion. An HMAC proves
possession of the shared secret, not authorship by an independent party; verifying an
externally preserved head/count detects rollback and complete-file truncation.
"""
from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat

from .adapter import _reject_duplicates

_DOMAIN = b'OMEGA-X-PROOF-STREAM-V1\0'
_GENESIS = '0'*64
_TYPE = re.compile(r'[A-Z][A-Z0-9_]{0,47}\Z')
_MAX_LINE = 8192
_MAX_BYTES = 32 * 1024 * 1024


class IntegrityViolation(ValueError):
    """Evidence was corrupted, noncanonical, truncated or wrongly authenticated."""


def _canonical(document: dict) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


class ProofStream:
    """Private owner-operated evidence log; append is linearized by advisory flock."""

    def __init__(self, path: str | Path, key: bytes, *, max_records: int = 4096):
        if type(key) is not bytes or len(key) != 32:
            raise ValueError('proof stream requires a 256-bit HMAC key')
        if type(max_records) is not int or not 1 <= max_records <= 4096:
            raise ValueError('record limit outside [1,4096]')
        self.path = Path(path)
        if self.path.name in ('', '.', '..') or self.path.is_symlink():
            raise PermissionError('unsafe evidence file')
        parent = self.path.parent
        if not parent.is_dir() or parent.is_symlink():
            raise PermissionError('evidence parent must be an existing directory')
        mode = parent.stat()
        if mode.st_uid != os.geteuid() or stat.S_IMODE(mode.st_mode) & 0o077:
            raise PermissionError('evidence directory must be private and owned')
        self._key = key
        self.max_records = max_records
        if self.path.exists():
            self._check_file(self.path.stat())

    @staticmethod
    def _check_file(meta: os.stat_result) -> None:
        if not stat.S_ISREG(meta.st_mode) or stat.S_IMODE(meta.st_mode) != 0o600 or meta.st_uid != os.geteuid():
            raise PermissionError('evidence file must be owner-only regular file')
        if meta.st_size > _MAX_BYTES:
            raise IntegrityViolation('evidence file exceeds configured capacity')

    def _open(self, *, create: bool = True) -> int:
        flags = os.O_RDWR | os.O_CLOEXEC | getattr(os, 'O_NOFOLLOW', 0)
        try:
            fd = os.open(self.path, flags)
        except FileNotFoundError:
            if not create:
                raise IntegrityViolation('evidence file missing')
            try:
                fd = os.open(self.path, flags | os.O_CREAT | os.O_EXCL, 0o600)
                # fsync the parent entry after creation, before acknowledging records.
                parent_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
            except FileExistsError:
                fd = os.open(self.path, flags)
        try:
            self._check_file(os.fstat(fd))
        except BaseException:
            os.close(fd)
            raise
        return fd

    def _scan(self, file) -> dict:
        file.seek(0)
        head, count = _GENESIS, 0
        total = 0
        while True:
            raw = file.readline(_MAX_LINE + 1)
            if not raw:
                break
            total += len(raw)
            if len(raw) > _MAX_LINE or total > _MAX_BYTES or not raw.endswith(b'\n'):
                raise IntegrityViolation('partial or oversized record')
            if count >= self.max_records:
                raise IntegrityViolation('record count exceeds allowed limit')
            try:
                record = json.loads(raw, object_pairs_hook=_reject_duplicates)
                if not isinstance(record, dict) or set(record) != {'seq', 'previous', 'kind', 'payload', 'digest', 'mac'}:
                    raise ValueError('record schema mismatch')
                if type(record['seq']) is not int or record['seq'] != count + 1:
                    raise ValueError('noncontiguous sequence')
                if record['previous'] != head or not isinstance(record['kind'], str) or not _TYPE.fullmatch(record['kind']):
                    raise ValueError('invalid prev hash or kind')
                body = {k: record[k] for k in ('seq', 'previous', 'kind', 'payload')}
                payload = _canonical(body)
                if len(payload) > _MAX_LINE - 160:
                    raise ValueError('oversized canonical body')
                digest = hashlib.sha256(_DOMAIN + payload).hexdigest()
                mac = hmac.new(self._key, _DOMAIN + digest.encode('ascii'), hashlib.sha256).hexdigest()
                if (type(record['digest']) is not str or type(record['mac']) is not str
                    or not hmac.compare_digest(digest, record['digest'])
                    or not hmac.compare_digest(mac, record['mac'])):
                    raise ValueError('invalid digest or authentication code')
                if _canonical(record) + b'\n' != raw:
                    raise ValueError('noncanonical evidence record')
                head = digest
                count += 1
            except (ValueError, TypeError, KeyError, UnicodeError, OverflowError) as exc:
                raise IntegrityViolation(f'non-verifiable record at sequence {count + 1}') from exc
        return {'count': count, 'head': head, 'bytes': total, 'valid': True}

    def verify(self, *, expected_head: str | None = None, expected_count: int | None = None) -> dict:
        fd = self._open(create=False)
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            with os.fdopen(fd, 'r+b', closefd=False) as file:
                result = self._scan(file)
            if expected_head is not None and (not isinstance(expected_head, str) or
                                              not hmac.compare_digest(expected_head, result['head'])):
                raise IntegrityViolation('external checkpoint head mismatch')
            if expected_count is not None and (type(expected_count) is not int or expected_count != result['count']):
                raise IntegrityViolation('external checkpoint sequence mismatch')
            return result
        finally:
            os.close(fd)

    def append(self, kind: str, payload: dict) -> dict:
        if not isinstance(kind, str) or not _TYPE.fullmatch(kind):
            raise ValueError('invalid evidence event kind')
        if not isinstance(payload, dict):
            raise ValueError('event payload must be a JSON object')
        # Validate serialization before creating files or acquiring I/O locks.
        _canonical(payload)
        fd = self._open()
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            with os.fdopen(fd, 'r+b', closefd=False) as file:
                prior = self._scan(file)
                if prior['count'] >= self.max_records:
                    raise ValueError('record limit reached')
                body = {'seq': prior['count'] + 1, 'previous': prior['head'],
                        'kind': kind, 'payload': payload}
                raw_body = _canonical(body)
                if len(raw_body) > _MAX_LINE - 160:
                    raise ValueError('event exceeds byte limit')
                digest = hashlib.sha256(_DOMAIN + raw_body).hexdigest()
                mac = hmac.new(self._key, _DOMAIN + digest.encode('ascii'), hashlib.sha256).hexdigest()
                record = _canonical({**body, 'digest': digest, 'mac': mac}) + b'\n'
                if len(record) > _MAX_LINE or prior['bytes'] + len(record) > _MAX_BYTES:
                    raise ValueError('evidence stream exceeds byte limit')
                file.seek(0, os.SEEK_END)
                file.write(record)
                file.flush()
                os.fsync(fd)
                return {'sequence': body['seq'], 'head': digest, 'bytes_written': len(record)}
        finally:
            os.close(fd)
