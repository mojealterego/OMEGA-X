"""Owner-operated loopback-only HTTP control plane for bounded real CPU jobs.

The service does not execute shell commands, bind public interfaces, attach BPF,
install dependencies, or modify external repositories. Every tenant owns a key.
"""
from __future__ import annotations

from dataclasses import dataclass
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import stat
import threading
import time
from urllib.parse import urlsplit

from .adapter import _reject_duplicates
from .executor import ExecutionRequest, LocalExecutor
from .host import detect_host
from .job_store import JobStore, Conflict, CapacityExceeded, validate_tenant

_MAX_BODY = 8192
_ID = re.compile(r'^/v1/jobs/([a-f0-9]{32})$')


def create_keys(path: str | Path, tenants: list[str]) -> None:
    if not tenants or len(tenants) > 64 or len(set(tenants)) != len(tenants):
        raise ValueError('tenant list must be unique and bounded')
    for tenant in tenants:
        validate_tenant(tenant)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os,'O_NOFOLLOW',0)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd,'w',encoding='ascii') as out:
            json.dump({'tenants': {tenant: secrets.token_hex(32) for tenant in tenants}},out,sort_keys=True)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def load_keys(path: str | Path) -> dict[str,bytes]:
    fd = os.open(path, os.O_RDONLY | getattr(os,'O_NOFOLLOW',0) | getattr(os,'O_CLOEXEC',0))
    try:
        mode = os.fstat(fd)
        if not stat.S_ISREG(mode.st_mode) or stat.S_IMODE(mode.st_mode) != 0o600:
            raise PermissionError('key file must be a regular file with mode 0600')
        if mode.st_uid != os.geteuid():
            raise PermissionError('key file must be owned by the current user')
        if mode.st_size > 8192:
            raise ValueError('key file exceeds limit')
        with os.fdopen(fd,'rb',closefd=False) as stream:
            data = stream.read(8193)
        body = json.loads(data,object_pairs_hook=_reject_duplicates)
        if not isinstance(body,dict) or set(body) != {'tenants'} or not isinstance(body['tenants'],dict):
            raise ValueError('invalid key file schema')
        if not 1 <= len(body['tenants']) <= 64:
            raise ValueError('invalid number of tenants')
        result = {}
        for tenant,key in body['tenants'].items():
            validate_tenant(tenant)
            if not isinstance(key,str) or not re.fullmatch('[0-9a-f]{64}',key):
                raise ValueError('keys must be 256-bit lowercase hex')
            result[tenant] = bytes.fromhex(key)
        if len(set(result.values())) != len(result):
            raise ValueError('tenant keys must be distinct')
        return result
    finally:
        os.close(fd)


class _LoopbackHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class LocalControlPlane:
    """Start/stop an authenticated server and a durable, fair worker pool."""

    def __init__(self, state_path: str | Path, keys: dict[str,bytes], *, host: str='127.0.0.1',
                 port: int=0, workers: int=2, max_pending: int=256):
        if host != '127.0.0.1':
            raise ValueError('only literal IPv4 loopback binding is permitted')
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError('invalid port')
        if type(workers) is not int or not 1 <= workers <= 16:
            raise ValueError('workers must be in [1,16]')
        if not isinstance(keys,dict) or not keys:
            raise ValueError('tenant keys required')
        for tenant,key in keys.items():
            validate_tenant(tenant)
            if type(key) is not bytes or len(key) != 32:
                raise ValueError('each tenant requires a 256-bit key')
        if len(set(keys.values())) != len(keys):
            raise ValueError('tenant keys must be distinct')
        self._keys = dict(keys)
        self.store = JobStore(state_path, max_pending=max_pending,
                              max_per_tenant=max(1,min(64,max_pending)))
        self._workers_count = workers
        self._stop = threading.Event()
        self._fault = threading.Event()
        self._threads: list[threading.Thread] = []
        self._server = _LoopbackHTTPServer((host,port), self._make_handler())
        self.port = self._server.server_port
        self._server_thread: threading.Thread | None = None
        self._started = False

    def _authenticate(self, authorization: str | None) -> str | None:
        if not authorization or len(authorization) > 256 or not authorization.startswith('Bearer '):
            return None
        candidate = authorization[7:]
        found = None
        for tenant,key in self._keys.items():
            if hmac.compare_digest(candidate, key.hex()):
                found = tenant
        return found

    def _make_handler(self):
        plane = self

        class Handler(BaseHTTPRequestHandler):
            server_version = 'OMEGA-X/4'
            sys_version = ''

            def log_message(self, fmt, *args):
                # No credentials, tenant IDs or request bodies in access logs.
                return

            def _send(self, status: int, body: dict):
                raw = json.dumps(body,sort_keys=True,allow_nan=False,separators=(',',':')).encode()
                self.send_response(status)
                self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Content-Length',str(len(raw)))
                self.send_header('Cache-Control','no-store')
                self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Connection','close')
                self.end_headers()
                self.wfile.write(raw)

            def _body(self) -> dict:
                if self.headers.get('Transfer-Encoding'):
                    raise ValueError('chunked and transfer encodings forbidden')
                if self.headers.get('Content-Type') != 'application/json':
                    raise ValueError('Content-Type must be application/json')
                length = self.headers.get('Content-Length')
                if length is None or not length.isdecimal() or not 0 < int(length) <= _MAX_BODY:
                    raise ValueError('request body size invalid')
                raw = self.rfile.read(int(length))
                if len(raw) != int(length):
                    raise ValueError('incomplete request body')
                body = json.loads(raw,object_pairs_hook=_reject_duplicates)
                if not isinstance(body,dict):
                    raise ValueError('JSON object required')
                return body

            def _dispatch(self):
                if self.headers.get('Host') != f'127.0.0.1:{plane.port}':
                    self._send(400,{'error':'INVALID_HOST'})
                    return
                path = urlsplit(self.path)
                if path.query or path.fragment or path.path != self.path:
                    self._send(400,{'error':'INVALID_PATH'})
                    return
                if self.command == 'GET' and path.path == '/v1/health':
                    self._send(503 if plane._fault.is_set() else 200,
                               {'status':'fault' if plane._fault.is_set() else 'ok',
                                'service':'OMEGA-X','mode':'local_cpu'})
                    return
                tenant = plane._authenticate(self.headers.get('Authorization'))
                if tenant is None:
                    self._send(401,{'error':'UNAUTHORIZED'})
                    return
                try:
                    if plane._fault.is_set():
                        self._send(503,{'error':'SERVICE_UNAVAILABLE'})
                        return
                    if self.command == 'GET' and path.path == '/v1/metrics':
                        self._send(200,plane.store.metrics(tenant))
                    elif self.command == 'GET' and path.path == '/v1/capabilities':
                        self._send(200,{'host':detect_host().to_dict(),
                                        'operations':['sha256','saxpy','memory'],
                                        'accelerator':'CPU','hardware_npu':False})
                    elif self.command == 'POST' and path.path == '/v1/jobs':
                        body = self._body()
                        allowed = {'idempotency_key','kind','size','cpu','timeout_s','priority'}
                        if set(body)-allowed or not {'idempotency_key','kind','size'} <= set(body):
                            raise ValueError('invalid job fields')
                        request = {'kind':body['kind'],'size':body['size'],'cpu':body.get('cpu'),
                                   'timeout_s':body.get('timeout_s',5.0),'priority':body.get('priority','normal')}
                        job = plane.store.submit(tenant,body['idempotency_key'],request)
                        self._send(200 if job['duplicate'] else 202,
                                   {'job_id':job['job_id'],'status':job['status']})
                    elif self.command in ('GET','DELETE') and (match := _ID.fullmatch(path.path)):
                        job_id = match.group(1)
                        job = plane.store.get(tenant,job_id)
                        if job is None:
                            self._send(404,{'error':'NOT_FOUND'})
                        elif self.command == 'GET':
                            self._send(200,job)
                        elif plane.store.cancel(tenant,job_id):
                            self._send(200,{'job_id':job_id,'status':'CANCELLED'})
                        else:
                            self._send(409,{'error':'JOB_NOT_CANCELLABLE'})
                    else:
                        self._send(404,{'error':'NOT_FOUND'})
                except Conflict:
                    self._send(409,{'error':'IDEMPOTENCY_CONFLICT'})
                except CapacityExceeded:
                    self._send(429,{'error':'CAPACITY_EXCEEDED'})
                except (ValueError,TypeError,json.JSONDecodeError):
                    self._send(400,{'error':'INVALID_REQUEST'})
                except (OSError,RuntimeError):
                    self._send(503,{'error':'SERVICE_UNAVAILABLE'})

            def do_GET(self):
                self._dispatch()

            def do_POST(self):
                self._dispatch()

            def do_DELETE(self):
                self._dispatch()

        return Handler

    def _worker(self):
        try:
            executor = LocalExecutor()
            while not self._stop.is_set():
                job = self.store.claim_next()
                if job is None:
                    self._stop.wait(.025)
                    continue
                req = job['request']
                try:
                    result = executor.run_one(ExecutionRequest(req['kind'],req['size'],req['cpu']),req['timeout_s'])
                    self.store.complete(job['job_id'],result)
                except TimeoutError:
                    self.store.fail(job['job_id'],'WORKER_TIMEOUT')
                except (OSError,RuntimeError,ValueError):
                    self.store.fail(job['job_id'],'WORKER_ERROR')
        except Exception:
            # Storage and invariant failures must stop dispatch, not disappear in a thread.
            self._fault.set()
            self._stop.set()

    def start(self):
        if self._started:
            raise RuntimeError('service already started')
        if not self.store.integrity():
            raise RuntimeError('durable journal integrity verification failed')
        self.store.recover()
        self._started = True
        self._threads = [threading.Thread(target=self._worker,name=f'omega-worker-{i}')
                         for i in range(self._workers_count)]
        for thread in self._threads:
            thread.start()
        self._server_thread = threading.Thread(target=self._server.serve_forever,name='omega-http')
        self._server_thread.start()

    def stop(self):
        if not self._started:
            self._server.server_close()
            return
        self._stop.set()
        self._server.shutdown()
        self._server.server_close()
        if self._server_thread is not None:
            self._server_thread.join(timeout=5)
        for thread in self._threads:
            thread.join(timeout=35)
        if any(thread.is_alive() for thread in self._threads):
            raise RuntimeError('worker did not terminate within its deadline')
        self._started = False
