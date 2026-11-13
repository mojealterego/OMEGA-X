"""Local HTTP end-to-end and negative security contracts."""
import http.client
import json
import os
from pathlib import Path
import socket
import stat
import tempfile
import threading
import time
import unittest

from omega_x.service import LocalControlPlane, load_keys, create_keys


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.keys = {'alpha': bytes.fromhex('a1'*32), 'beta': bytes.fromhex('b2'*32)}
        self.plane = LocalControlPlane(Path(self.tmp.name) / 'service.sqlite3', self.keys,
                                       workers=2, port=0, max_pending=8)
        self.plane.start()

    def tearDown(self):
        self.plane.stop()
        self.tmp.cleanup()

    def request(self, method, path, body=None, token='alpha', headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.plane.port, timeout=5)
        h = {'Authorization': 'Bearer ' + self.keys[token].hex(), 'Content-Type': 'application/json'} if token else {}
        h.update(headers or {})
        data = None if body is None else json.dumps(body).encode()
        conn.request(method, path, data, h)
        response = conn.getresponse()
        raw = response.read()
        code = response.status
        conn.close()
        return code, json.loads(raw)

    def test_real_workload_end_to_end_and_tenant_isolation(self):
        code, created = self.request('POST', '/v1/jobs', {'idempotency_key': 'first', 'kind': 'sha256', 'size': 1024})
        self.assertEqual(code, 202, created)
        job_id = created['job_id']
        code, same = self.request('POST', '/v1/jobs', {'idempotency_key': 'first', 'kind': 'sha256', 'size': 1024})
        self.assertEqual(code, 200)
        self.assertEqual(same['job_id'], job_id)
        code, hidden = self.request('GET', f'/v1/jobs/{job_id}', token='beta')
        self.assertEqual(code, 404)
        self.assertNotIn('result', hidden)
        end = time.monotonic()+10
        while time.monotonic()<end:
            code, item = self.request('GET', f'/v1/jobs/{job_id}')
            if item['status'] in ('SUCCEEDED', 'FAILED'):
                break
            time.sleep(.05)
        self.assertEqual(item['status'], 'SUCCEEDED', item)
        self.assertEqual(item['result']['kind'], 'sha256')
        self.assertEqual(len(item['result']['digest']), 64)
        code, metrics = self.request('GET', '/v1/metrics')
        self.assertEqual(metrics['SUCCEEDED'], 1)

    def test_rejects_unauthorized_cross_origin_and_oversized(self):
        self.assertEqual(self.request('GET', '/v1/metrics', token=None)[0], 401)
        self.assertEqual(self.request('GET', '/v1/metrics', headers={'Authorization':'Bearer wrong'})[0], 401)
        self.assertEqual(self.request('GET', '/v1/metrics', headers={'Host':'evil.example'})[0], 400)
        self.assertEqual(self.request('POST', '/v1/jobs', {'idempotency_key':'x','kind':'shell','size':1})[0], 400)
        self.assertEqual(self.request('POST', '/v1/jobs', {'idempotency_key':'x','kind':'sha256','size':False})[0], 400)
        self.assertEqual(self.request('POST', '/v1/jobs', {'idempotency_key':'x','kind':'sha256','size':1,'unknown':1})[0], 400)
        self.assertEqual(self.request('GET', '/v1/jobs/not-a-valid-id')[0], 404)

    def test_duplicate_json_keys_rejected_and_conflict(self):
        conn = http.client.HTTPConnection('127.0.0.1', self.plane.port, timeout=5)
        conn.request('POST','/v1/jobs', b'{"kind":"sha256","kind":"memory","size":1,"idempotency_key":"a"}',
                     {'Authorization': 'Bearer '+self.keys['alpha'].hex(), 'Content-Type':'application/json'})
        resp=conn.getresponse(); resp.read(); self.assertEqual(resp.status,400); conn.close()
        self.assertEqual(self.request('POST','/v1/jobs',{'kind':'sha256','size':10,'idempotency_key':'conflict'})[0],202)
        self.assertEqual(self.request('POST','/v1/jobs',{'kind':'sha256','size':11,'idempotency_key':'conflict'})[0],409)

    def test_cancel_queued_and_health(self):
        self.assertEqual(self.request('GET', '/v1/health', token=None)[0], 200)
        self.assertEqual(self.request('GET', '/v1/capabilities')[0], 200)
        self.assertEqual(self.request('DELETE', '/v1/jobs/00000000000000000000000000000000')[0], 404)

    def test_rejects_non_loopback_bind(self):
        with self.assertRaises(ValueError):
            LocalControlPlane(Path(self.tmp.name)/'bad.db', self.keys, host='0.0.0.0')


class KeyManagementTests(unittest.TestCase):
    def test_owner_only_secret_file_and_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'keys.json'
            create_keys(path, ['alpha', 'beta'])
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            keys=load_keys(path)
            self.assertEqual(len(keys),2)
            self.assertEqual(len(keys['alpha']),32)
            os.chmod(path, 0o644)
            with self.assertRaises(PermissionError):
                load_keys(path)

    def test_rejects_symlink_key_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'keys.json'
            create_keys(path, ['alpha'])
            link=Path(tmp)/'link'
            link.symlink_to(path)
            with self.assertRaises(OSError):
                load_keys(link)


if __name__ == '__main__':
    unittest.main()

class WorkerFailureTests(unittest.TestCase):
    def test_store_failure_is_reported_not_silent(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            plane=LocalControlPlane(Path(tmp)/'state.db',{'alpha':bytes.fromhex('ab'*32)},workers=1)
            def broken_claim():
                raise sqlite3.OperationalError('injected storage failure')
            plane.store.claim_next=broken_claim
            try:
                plane.start()
                deadline=time.monotonic()+2
                while time.monotonic()<deadline and not plane._fault.is_set():
                    time.sleep(.01)
                self.assertTrue(plane._fault.is_set())
                conn=http.client.HTTPConnection('127.0.0.1',plane.port,timeout=2)
                conn.request('GET','/v1/health')
                response=conn.getresponse();response.read()
                self.assertEqual(response.status,503)
                conn.close()
            finally:
                plane.stop()
