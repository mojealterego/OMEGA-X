"""Offline admission prevents simulated kernel availability claims."""
from __future__ import annotations
import sys
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kernel_ebpf'))
from preflight import inspect_host

class TestScxPreflight(unittest.TestCase):
    def test_missing_kernel_capabilities_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            caps = inspect_host(root/'none', root/'no-btf')
            self.assertEqual(caps['status'], 'UNAVAILABLE_FOR_KERNEL_RUNTIME_VALIDATION')
            self.assertFalse(caps['bpf_build_verified'])
            self.assertFalse(caps['kernel_attach_verified'])

    def test_fake_sysfs_does_not_claim_actual_kernel_attachment(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root/'scx').mkdir()
            (root/'btf').write_bytes(b'btf')
            caps = inspect_host(root/'scx', root/'btf')
            self.assertFalse(caps['kernel_attach_verified'])

if __name__ == '__main__':
    unittest.main()
