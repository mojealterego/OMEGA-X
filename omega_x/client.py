"""Minimal authenticated loopback client, no third-party dependencies."""
from __future__ import annotations

import http.client
import json
import re
import secrets
import time

from .job_store import validate_request


class RemoteError(RuntimeError):
    def __init__(self, status: int, code: str):
        self.status = status
        self.code = code
        super().__init__(f'OMEGA-X HTTP {status}: {code}')


class OmegaClient:
    def __init__(self, key: bytes, *, host: str='127.0.0.1', port: int=8765, timeout_s: float=5.0):
        if host != '127.0.0.1':
            raise ValueError('only literal loopback host is allowed')
        if type(key) is not bytes or len(key) != 32:
            raise ValueError('client key must be 256 bits')
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('invalid port')
        if not isinstance(timeout_s,(int,float)) or isinstance(timeout_s,bool) or not 0 < timeout_s <= 30:
            raise ValueError('invalid HTTP timeout')
        self._key = key
        self._host = host
        self._port = port
        self._timeout_s = timeout_s

    def _request(self, method: str, path: str, body: dict | None=None, *, auth: bool=True) -> dict:
        data = None if body is None else json.dumps(body,sort_keys=True,separators=(',',':')).encode()
        headers = {'Content-Type':'application/json'}
        if auth:
            headers['Authorization'] = 'Bearer '+self._key.hex()
        connection = http.client.HTTPConnection(self._host,self._port,timeout=self._timeout_s)
        try:
            connection.request(method,path,data,headers)
            response = connection.getresponse()
            raw = response.read(65537)
            if len(raw)>65536:
                raise RuntimeError('server response exceeds limit')
            result = json.loads(raw)
            if not isinstance(result,dict):
                raise RuntimeError('unexpected server response')
            if not 200 <= response.status < 300:
                raise RemoteError(response.status,str(result.get('error','REMOTE_FAILURE')))
            return result
        finally:
            connection.close()

    def submit(self, kind: str, size: int, *, idempotency_key: str | None=None,
               cpu: int | None=None, timeout_s: float=5.0, priority: str='normal') -> dict:
        request = validate_request({'kind':kind,'size':size,'cpu':cpu,
                                    'timeout_s':timeout_s,'priority':priority})
        key = idempotency_key if idempotency_key is not None else secrets.token_hex(16)
        return self._request('POST','/v1/jobs',{'idempotency_key':key,**request})

    @staticmethod
    def _check_job(job_id: str) -> str:
        if not isinstance(job_id,str) or not re.fullmatch(r'[a-f0-9]{32}',job_id):
            raise ValueError('invalid job id')
        return job_id

    def get(self, job_id: str) -> dict:
        return self._request('GET','/v1/jobs/'+self._check_job(job_id))

    def cancel(self, job_id: str) -> dict:
        return self._request('DELETE','/v1/jobs/'+self._check_job(job_id))

    def metrics(self) -> dict:
        return self._request('GET','/v1/metrics')

    def capabilities(self) -> dict:
        return self._request('GET','/v1/capabilities')

    def health(self) -> dict:
        return self._request('GET','/v1/health',auth=False)

    def wait(self, job_id: str, *, timeout_s: float=30.0, interval_s: float=.05) -> dict:
        if not isinstance(timeout_s,(int,float)) or not 0 < timeout_s <= 3600:
            raise ValueError('invalid wait deadline')
        if not isinstance(interval_s,(int,float)) or not 0 < interval_s <= 10:
            raise ValueError('invalid polling interval')
        deadline = time.monotonic()+timeout_s
        while True:
            result = self.get(job_id)
            if result['status'] in ('SUCCEEDED','FAILED','CANCELLED'):
                return result
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError('job polling exceeded deadline')
            time.sleep(min(interval_s,remaining))
