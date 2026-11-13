"""End-to-end tests for the standalone local client library."""
import tempfile
from pathlib import Path
import unittest

from omega_x.client import OmegaClient, RemoteError
from omega_x.service import LocalControlPlane


class ClientTests(unittest.TestCase):
    def test_submit_poll_and_metrics(self):
        with tempfile.TemporaryDirectory() as root:
            token=bytes.fromhex('12'*32)
            service=LocalControlPlane(Path(root)/'jobs.db',{'alpha':token},workers=1)
            service.start()
            try:
                client=OmegaClient(token,port=service.port)
                result=client.submit('sha256',512,idempotency_key='client-test')
                self.assertEqual(result['status'],'QUEUED')
                final=client.wait(result['job_id'],timeout_s=10)
                self.assertEqual(final['status'],'SUCCEEDED')
                self.assertEqual(len(final['result']['digest']),64)
                self.assertEqual(client.metrics()['SUCCEEDED'],1)
                self.assertEqual(client.health()['status'],'ok')
            finally:
                service.stop()

    def test_auth_failure_and_invalid_host(self):
        with tempfile.TemporaryDirectory() as root:
            token=bytes.fromhex('12'*32)
            service=LocalControlPlane(Path(root)/'jobs.db',{'alpha':token},workers=1)
            service.start()
            try:
                client=OmegaClient(bytes.fromhex('13'*32),port=service.port)
                with self.assertRaises(RemoteError) as exc:
                    client.metrics()
                self.assertEqual(exc.exception.status,401)
                with self.assertRaises(ValueError):
                    OmegaClient(token,host='0.0.0.0',port=service.port)
            finally:
                service.stop()


if __name__=='__main__':
    unittest.main()
