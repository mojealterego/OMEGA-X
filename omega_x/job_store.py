"""Crash-recoverable, tenant-isolated, bounded SQLite WAL job journal.

A claim is durable before execution. Jobs are deterministic, allowlisted CPU
operations; a crash may cause at-least-once re-execution, never shell execution.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
import json
import math
from pathlib import Path
import re
import secrets
import os
import stat
import sqlite3
import time

from .executor import ExecutionRequest

_TENANT = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
_KEY = re.compile(r'^[A-Za-z0-9_.:-]{1,128}$')
_JOB_ID = re.compile(r'^[0-9a-f]{32}$')
_PRIORITY = {'latency': 0, 'normal': 1, 'background': 2}
_MAX_ATTEMPTS = 3


class Conflict(ValueError):
    """Idempotency key was reused with different arguments."""


class CapacityExceeded(ValueError):
    """Bounded queue or per-tenant quota was reached."""


def validate_tenant(tenant: str) -> str:
    if not isinstance(tenant, str) or not _TENANT.fullmatch(tenant):
        raise ValueError('invalid tenant identifier')
    return tenant


def validate_request(request: dict) -> dict:
    if not isinstance(request, dict) or set(request) != {'kind', 'size', 'cpu', 'timeout_s', 'priority'}:
        raise ValueError('invalid job request fields')
    validated = ExecutionRequest(request['kind'], request['size'], request['cpu'])
    timeout = request['timeout_s']
    if isinstance(timeout, bool) or not isinstance(timeout, (float, int)) or not math.isfinite(timeout) or not 0.05 <= timeout <= 30.0:
        raise ValueError('timeout must be finite in [0.05,30]')
    priority = request['priority']
    if not isinstance(priority, str) or priority not in _PRIORITY:
        raise ValueError('invalid priority')
    return {'kind': validated.kind, 'size': validated.size, 'cpu': validated.cpu,
            'timeout_s': float(timeout), 'priority': priority}


class JobStore:
    """Every operation uses its own connection; BEGIN IMMEDIATE serializes claims."""

    def __init__(self, path: str | Path, *, max_pending: int = 256, max_per_tenant: int = 64):
        if type(max_pending) is not int or not 1 <= max_pending <= 65536:
            raise ValueError('invalid global queue bound')
        if type(max_per_tenant) is not int or not 1 <= max_per_tenant <= max_pending:
            raise ValueError('invalid tenant queue bound')
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        parent = self.path.parent
        if parent.is_symlink() or stat.S_IMODE(parent.stat().st_mode) & 0o077:
            raise PermissionError('database directory must be private (0700)')
        if self.path.is_symlink():
            raise OSError('database symlinks forbidden')
        if self.path.exists():
            info = self.path.stat()
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.geteuid():
                raise PermissionError('database must be owned and mode 0600')
        else:
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            os.close(fd)
        self.max_pending = max_pending
        self.max_per_tenant = max_per_tenant
        with self._connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    tenant TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    not_before_ns INTEGER NOT NULL,
                    created_ns INTEGER NOT NULL,
                    updated_ns INTEGER NOT NULL,
                    result_json TEXT,
                    error_code TEXT,
                    UNIQUE(tenant,idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_queue ON jobs(status,not_before_ns,tenant,priority,created_ns);
                CREATE INDEX IF NOT EXISTS idx_jobs_tenant ON jobs(tenant,status);
                CREATE TABLE IF NOT EXISTS tenant_turns (tenant TEXT PRIMARY KEY, turn INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
                INSERT OR IGNORE INTO counters VALUES ('turn',0);
                CREATE TABLE IF NOT EXISTS journal (
                    seq INTEGER PRIMARY KEY, job_id TEXT NOT NULL, tenant TEXT NOT NULL,
                    event TEXT NOT NULL, created_ns INTEGER NOT NULL,
                    previous_hash TEXT NOT NULL, record_hash TEXT NOT NULL
                );
            ''')

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, isolation_level=None, timeout=5)
        try:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA busy_timeout=5000')
            db.execute('PRAGMA synchronous=FULL')
            yield db
        finally:
            db.close()

    @staticmethod
    def _append_audit(db: sqlite3.Connection, job_id: str, tenant: str, event: str, now_ns: int):
        last = db.execute('SELECT seq,record_hash FROM journal ORDER BY seq DESC LIMIT 1').fetchone()
        seq = (last['seq']+1) if last else 1
        previous = last['record_hash'] if last else '0'*64
        material = json.dumps([seq,job_id,tenant,event,now_ns,previous],separators=(',',':'))
        digest = hashlib.sha256(material.encode()).hexdigest()
        db.execute('''INSERT INTO journal VALUES (?,?,?,?,?,?,?)''',
                   (seq,job_id,tenant,event,now_ns,previous,digest))

    @staticmethod
    def _verify_audit(db: sqlite3.Connection) -> bool:
        previous = '0'*64
        expected_seq = 1
        for row in db.execute('SELECT * FROM journal ORDER BY seq'):
            if row['seq'] != expected_seq or row['previous_hash'] != previous:
                return False
            material = json.dumps([row['seq'],row['job_id'],row['tenant'],row['event'],
                                   row['created_ns'],row['previous_hash']],separators=(',',':'))
            digest = hashlib.sha256(material.encode()).hexdigest()
            if not secrets.compare_digest(digest,row['record_hash']):
                return False
            previous = digest
            expected_seq += 1
        return True

    @staticmethod
    def _view(row: sqlite3.Row) -> dict:
        result = {'job_id': row['job_id'], 'tenant': row['tenant'], 'status': row['status'],
                  'attempts': row['attempts'], 'not_before_ns': row['not_before_ns'],
                  'created_ns': row['created_ns'], 'updated_ns': row['updated_ns'],
                  'error_code': row['error_code']}
        if row['result_json'] is not None:
            result['result'] = json.loads(row['result_json'])
        return result

    def submit(self, tenant: str, idempotency_key: str, request: dict, *, now_ns: int | None = None) -> dict:
        tenant = validate_tenant(tenant)
        if not isinstance(idempotency_key, str) or not _KEY.fullmatch(idempotency_key):
            raise ValueError('invalid idempotency key')
        req = validate_request(request)
        now_ns = time.time_ns() if now_ns is None else now_ns
        if type(now_ns) is not int or not 0 <= now_ns < 2**63:
            raise ValueError('invalid clock')
        raw = json.dumps(req, sort_keys=True, separators=(',', ':'), allow_nan=False)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                old = db.execute('SELECT * FROM jobs WHERE tenant=? AND idempotency_key=?',
                                 (tenant, idempotency_key)).fetchone()
                if old is not None:
                    if old['payload_sha256'] != digest:
                        raise Conflict('idempotency key conflicts with existing job')
                    result = self._view(old)
                    result['duplicate'] = True
                else:
                    total = db.execute("SELECT count(*) FROM jobs WHERE status IN ('QUEUED','RUNNING')").fetchone()[0]
                    own = db.execute("SELECT count(*) FROM jobs WHERE tenant=? AND status IN ('QUEUED','RUNNING')", (tenant,)).fetchone()[0]
                    if total >= self.max_pending or own >= self.max_per_tenant:
                        raise CapacityExceeded('bounded pending capacity exceeded')
                    job_id = secrets.token_hex(16)
                    db.execute('''INSERT INTO jobs
                        (job_id,tenant,idempotency_key,payload_sha256,request_json,priority,status,
                         not_before_ns,created_ns,updated_ns)
                        VALUES (?,?,?,?,?,?,'QUEUED',?,?,?)''',
                        (job_id,tenant,idempotency_key,digest,raw,_PRIORITY[req['priority']],now_ns,now_ns,now_ns))
                    result = self._view(db.execute('SELECT * FROM jobs WHERE job_id=?', (job_id,)).fetchone())
                    result['duplicate'] = False
                    self._append_audit(db,job_id,tenant,'SUBMITTED',now_ns)
                db.execute('COMMIT')
                return result
            except BaseException:
                db.execute('ROLLBACK')
                raise

    def claim_next(self, now_ns: int | None = None) -> dict | None:
        now_ns = time.time_ns() if now_ns is None else now_ns
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                # Tenant fairness first; priority and FIFO within each tenant.
                row = db.execute('''SELECT j.* FROM jobs j
                    LEFT JOIN tenant_turns t ON t.tenant=j.tenant
                    WHERE j.status='QUEUED' AND j.not_before_ns <= ?
                    ORDER BY COALESCE(t.turn,0), j.tenant, j.priority, j.created_ns, j.job_id LIMIT 1''',
                    (now_ns,)).fetchone()
                if row is None:
                    db.execute('COMMIT')
                    return None
                db.execute("UPDATE counters SET value=value+1 WHERE name='turn'")
                turn = db.execute("SELECT value FROM counters WHERE name='turn'").fetchone()[0]
                db.execute('''INSERT INTO tenant_turns(tenant,turn) VALUES (?,?)
                    ON CONFLICT(tenant) DO UPDATE SET turn=excluded.turn''', (row['tenant'],turn))
                db.execute('''UPDATE jobs SET status='RUNNING', attempts=attempts+1,updated_ns=?
                              WHERE job_id=? AND status='QUEUED' ''', (now_ns,row['job_id']))
                self._append_audit(db,row['job_id'],row['tenant'],'CLAIMED',now_ns)
                job = db.execute('SELECT * FROM jobs WHERE job_id=?',(row['job_id'],)).fetchone()
                db.execute('COMMIT')
                result = self._view(job)
                result['request'] = json.loads(job['request_json'])
                return result
            except BaseException:
                db.execute('ROLLBACK')
                raise

    def complete(self, job_id: str, result: dict, now_ns: int | None = None) -> bool:
        if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
            raise ValueError('invalid job id')
        raw = json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False)
        if len(raw) > 65536:
            raise ValueError('job result exceeds limit')
        now_ns = time.time_ns() if now_ns is None else now_ns
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                row = db.execute("SELECT tenant FROM jobs WHERE job_id=? AND status='RUNNING'",(job_id,)).fetchone()
                if row is None:
                    db.execute('COMMIT')
                    return False
                db.execute('''UPDATE jobs SET status='SUCCEEDED',result_json=?,error_code=NULL,updated_ns=?
                                   WHERE job_id=? AND status='RUNNING' ''',(raw,now_ns,job_id))
                self._append_audit(db,job_id,row['tenant'],'SUCCEEDED',now_ns)
                db.execute('COMMIT')
                return True
            except BaseException:
                db.execute('ROLLBACK')
                raise

    def fail(self, job_id: str, code: str, now_ns: int | None = None) -> bool:
        if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
            raise ValueError('invalid job id')
        if not isinstance(code, str) or not re.fullmatch(r'[A-Z_]{1,48}',code):
            raise ValueError('invalid error code')
        now_ns = time.time_ns() if now_ns is None else now_ns
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                row = db.execute('SELECT attempts,status,tenant FROM jobs WHERE job_id=?',(job_id,)).fetchone()
                if row is None or row['status'] != 'RUNNING':
                    db.execute('COMMIT')
                    return False
                if row['attempts'] >= _MAX_ATTEMPTS:
                    status, due = 'FAILED', now_ns
                else:
                    attempt = row['attempts']
                    jitter = int.from_bytes(hashlib.sha256(f'{job_id}:{attempt}'.encode()).digest()[:4],'big') % 50_000_000
                    due = now_ns + 100_000_000 * (2 ** (attempt-1)) + jitter
                    status = 'QUEUED'
                db.execute('''UPDATE jobs SET status=?,not_before_ns=?,updated_ns=?,error_code=?
                              WHERE job_id=? AND status='RUNNING' ''',(status,due,now_ns,code,job_id))
                self._append_audit(db,job_id,row['tenant'],'FAILED' if status=='FAILED' else 'RETRY',now_ns)
                db.execute('COMMIT')
                return True
            except BaseException:
                db.execute('ROLLBACK')
                raise

    def recover(self, now_ns: int | None = None) -> int:
        now_ns = time.time_ns() if now_ns is None else now_ns
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                rows = db.execute("SELECT job_id,tenant,attempts FROM jobs WHERE status='RUNNING'").fetchall()
                for row in rows:
                    status = 'FAILED' if row['attempts'] >= _MAX_ATTEMPTS else 'QUEUED'
                    db.execute('''UPDATE jobs SET status=?,not_before_ns=?,updated_ns=?,error_code='RECOVERED'
                                  WHERE job_id=?''',(status,now_ns,now_ns,row['job_id']))
                    self._append_audit(db,row['job_id'],row['tenant'],'RECOVERED' if status=='QUEUED' else 'FAILED',now_ns)
                db.execute('COMMIT')
                return len(rows)
            except BaseException:
                db.execute('ROLLBACK')
                raise

    def cancel(self, tenant: str, job_id: str, now_ns: int | None = None) -> bool:
        validate_tenant(tenant)
        if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
            return False
        now_ns = time.time_ns() if now_ns is None else now_ns
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                cur = db.execute("UPDATE jobs SET status='CANCELLED',updated_ns=? WHERE tenant=? AND job_id=? AND status='QUEUED'",
                                 (now_ns,tenant,job_id))
                if cur.rowcount:
                    self._append_audit(db,job_id,tenant,'CANCELLED',now_ns)
                db.execute('COMMIT')
                return cur.rowcount == 1
            except BaseException:
                db.execute('ROLLBACK')
                raise

    def get(self, tenant: str, job_id: str) -> dict | None:
        validate_tenant(tenant)
        if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
            return None
        with self._connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE tenant=? AND job_id=?',(tenant,job_id)).fetchone()
            return self._view(row) if row else None

    def metrics(self, tenant: str) -> dict:
        validate_tenant(tenant)
        with self._connect() as db:
            counts = dict(db.execute('SELECT status,count(*) FROM jobs WHERE tenant=? GROUP BY status',(tenant,)).fetchall())
        return {'tenant': tenant, 'total': sum(counts.values()),
                **{state: counts.get(state,0) for state in ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')}}

    def integrity(self) -> bool:
        with self._connect() as db:
            return db.execute('PRAGMA quick_check').fetchone()[0] == 'ok' and self._verify_audit(db)
