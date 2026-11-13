"""Portable C11 reference policy verification, not a loaded kernel scheduler."""
import ctypes
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest

from omega_x.scx_contract import policy_choice


class SchedExtPolicyReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='omega_scx_contract_')
        cls.addClassCleanup(cls.tmp.cleanup)
        root = Path(__file__).resolve().parents[1]
        compiler = shutil.which('cc')
        if compiler is None:
            raise RuntimeError('C compiler required for native policy verification')
        output = Path(cls.tmp.name) / 'liboxscx.so'
        run = subprocess.run([compiler, '-std=c11', '-O2', '-fPIC', '-shared',
                              '-Wall', '-Wextra', '-Werror', '-pedantic',
                              '-o', str(output), str(root / 'kernel_ebpf/policy_reference.c')],
                             cwd=root, capture_output=True, text=True, timeout=20)
        if run.returncode:
            raise RuntimeError(f'C11 reference build failed: {run.stderr}')
        cls.lib = ctypes.CDLL(str(output))
        cls.lib.omega_scx_choice.argtypes = [ctypes.c_uint32]*5
        cls.lib.omega_scx_choice.restype = ctypes.c_uint32

    def assert_decision(self, opt_in, role, hint, p_count, e_count, expected):
        self.assertEqual(policy_choice(opt_in, role, hint, p_count, e_count), expected)
        self.assertEqual(self.lib.omega_scx_choice(opt_in, role, hint, p_count, e_count), expected)

    def test_never_schedules_without_opt_in(self):
        for role in range(4):
            for hint in range(4):
                self.assert_decision(0, role, hint, 10, 10, 0)

    def test_unknown_cpu_prefers_p_queue(self):
        self.assert_decision(1, 0, 0, 2, 3, 1)
        self.assert_decision(1, 0, 1, 0, 3, 2)

    def test_e_core_prefers_e_then_steals_p(self):
        self.assert_decision(1, 2, 1, 2, 3, 2)
        self.assert_decision(1, 2, 2, 2, 0, 1)
        self.assert_decision(1, 2, 2, 0, 0, 0)

    def test_p_core_prefers_p_then_steals_e(self):
        self.assert_decision(1, 1, 0, 3, 3, 1)
        self.assert_decision(1, 1, 1, 0, 1, 2)

    def test_randomized_python_c_contract_equivalence(self):
        rng = random.Random(115011)
        for _ in range(20_000):
            args = [rng.randrange(2), rng.randrange(4), rng.randrange(5), rng.randrange(32), rng.randrange(32)]
            self.assertEqual(self.lib.omega_scx_choice(*args), policy_choice(*args))

    def test_all_functions_bounded_and_static(self):
        for role in (0, 1, 2, 3, 0xFFFFFFFF):
            self.assertIn(self.lib.omega_scx_choice(1, role, 1, 2, 2), (1, 2))
        self.assert_decision(1, 0xFFFFFFFF, 0xFFFFFFFF, 0, 0, 0)


if __name__ == '__main__':
    unittest.main()
