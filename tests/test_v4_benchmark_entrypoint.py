"""Native benchmark must run directly from an unpacked archive."""
from pathlib import Path
import subprocess
import sys
import unittest


class BenchmarkEntrypointTests(unittest.TestCase):
    def test_direct_script_invocation(self):
        root=Path(__file__).resolve().parents[1]
        command=[sys.executable,str(root/'benchmarks/native_benchmark.py')]
        result=subprocess.run(command,cwd=root,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('observed_speedup',result.stdout)


if __name__=='__main__':
    unittest.main()
