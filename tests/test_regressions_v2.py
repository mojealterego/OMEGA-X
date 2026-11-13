"""Regression cases derived from the baseline implementation and adversarial inputs."""
import json
import unittest
from pathlib import Path
from omega_x.model import load_profile, Domain
from omega_x.cache import CacheHierarchy, PartitionedCache
from omega_x.adapter import decode
from omega_x.resilience import CircuitBreaker

ROOT = Path(__file__).resolve().parents[1]


class TestCacheCorrectness(unittest.TestCase):
    def test_l2_domains_cannot_share_cache_entries(self):
        cache = CacheHierarchy(load_profile(ROOT / 'config/profile.json'))
        cache.access(4096, 2, Domain.P)
        cache.access(4096, 8, Domain.E)
        self.assertNotEqual(cache.l2[(Domain.P, 2)], cache.l2[(Domain.E, 2)])
        self.assertEqual(len(cache.l2), 2)

    def test_nonstandard_line_bytes_do_not_alias_addresses(self):
        cache = PartitionedCache(8192, 4, 2, 128, 32)
        self.assertFalse(cache.access(0, Domain.P))
        self.assertTrue(cache.access(64, Domain.P))
        self.assertFalse(cache.access(128, Domain.P))


class TestSecurityValidation(unittest.TestCase):
    def test_duplicate_json_keys_rejected(self):
        raw = b'{"version":1,"version":1,"request_id":"a","tasks":[]}'
        with self.assertRaises(ValueError):
            decode(raw)

    def test_bool_as_task_id_rejected(self):
        task = {"task_id": True, "name":"a", "instruction":"SCALAR", "instructions":1,"working_set_bytes":1}
        raw = json.dumps({"version":1,"request_id":"a","tasks":[task]}).encode()
        with self.assertRaises(ValueError):
            decode(raw)

    def test_half_open_circuit_allows_only_one_probe(self):
        breaker = CircuitBreaker(1, 10)
        breaker.record(0, False)
        self.assertFalse(breaker.allow(9))
        self.assertTrue(breaker.allow(10))
        self.assertFalse(breaker.allow(10))
        breaker.record(10, True)
        self.assertTrue(breaker.allow(11))

if __name__ == '__main__':
    unittest.main()
