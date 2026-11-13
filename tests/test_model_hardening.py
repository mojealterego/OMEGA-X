"""Adversarial validation for public API input and bounded allocations."""
import unittest
from omega_x.model import Workload, Instruction, Profile, load_profile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestStrictModels(unittest.TestCase):
    def test_rejects_bool_instruction_count_and_noninteger_memory(self):
        for instructions, memory in ((True, 10), (10, 1.5), ('10', 10)):
            with self.assertRaises(ValueError):
                Workload(1, 'a', Instruction.SCALAR, instructions, memory)

    def test_rejects_nonstring_name_and_unbounded_instruction_count(self):
        for name, count in ((7, 10), ('valid', 2**63)):
            with self.assertRaises(ValueError):
                Workload(1, name, Instruction.SCALAR, count, 64)

    def test_rejects_unbounded_profile_cache_and_invalid_schema(self):
        data = load_profile(ROOT / 'config/profile.json').data
        changed = __import__('copy').deepcopy(data)
        changed['cache']['l3_bytes'] = 1 << 60
        with self.assertRaises(ValueError):
            Profile(changed)
        changed = __import__('copy').deepcopy(data)
        changed['schema_version'] = True
        with self.assertRaises(ValueError):
            Profile(changed)

if __name__ == '__main__':
    unittest.main()
