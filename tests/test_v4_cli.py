"""Real subprocess contract for the local control-plane CLI."""
import http.client
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


class ServiceCLITests(unittest.TestCase):
    def test_init_keys_and_serve_sigterm_shutdown(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            keys=root/'keys.json'
            state=root/'state'
            created=subprocess.run([sys.executable,'-m','omega_x.cli','init-keys',str(keys),'--tenants','alpha','beta'],
                                   capture_output=True,text=True,timeout=10)
            self.assertEqual(created.returncode,0,created.stderr)
            self.assertTrue(keys.is_file())
            proc=subprocess.Popen([sys.executable,'-m','omega_x.cli','serve','--keys-file',str(keys),
                                   '--state-dir',str(state),'--workers','1','--port','0'],
                                  stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                line=proc.stdout.readline().strip()
                status=json.loads(line)
                self.assertEqual(status['status'],'listening')
                self.assertEqual(status['host'],'127.0.0.1')
                port=status['port']
                conn=http.client.HTTPConnection('127.0.0.1',port,timeout=4)
                conn.request('GET','/v1/health')
                response=conn.getresponse()
                self.assertEqual(response.status,200)
                response.read();conn.close()
                proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=8)
                self.assertEqual(proc.returncode,0,proc.stderr.read())
            finally:
                if proc.poll() is None:
                    proc.kill();proc.wait(timeout=5)
                proc.stdout.close();proc.stderr.close()


if __name__ == '__main__':
    unittest.main()
