"""Zero-skipped stdlib regression, integration, negative and replay scenarios."""
import json
from pathlib import Path
import unittest
from omega_x.model import Workload, Instruction, Domain, load_profile, workload_from_dict
from omega_x.telemetry import criticality, composite
from omega_x.cache import PartitionedCache, CacheHierarchy
from omega_x.fabric import Fabric
from omega_x.scheduler import Scheduler
from omega_x.runtime import OmegaRuntime
from omega_x.resilience import CircuitBreaker, checkpoint, recover, retries
from omega_x.simulation import DeterministicTwin
from omega_x.adapter import encode, decode, idempotency_key

PROFILE = load_profile(Path(__file__).resolve().parents[1] / 'config' / 'profile.json')

def task(i, instruction=Instruction.CACHE):
    return Workload(i, f'job{i}', instruction, 300000, 8 * 1024**2, trace=(0, 64, 128, 0), cache_warmth=.8)

class TestModel(unittest.TestCase):
    def test_negative(self):
        with self.assertRaises(ValueError):
            Workload(1, 'x', Instruction.CACHE, -1, 0)
        with self.assertRaises(ValueError):
            Workload(1, 'x', Instruction.CACHE, 1, 0, sparsity=float('nan'))
        with self.assertRaises(ValueError):
            Workload(1, 'x', Instruction.CACHE, 1, 0, trace=(-1,))

    def test_criticality_bounds(self):
        self.assertTrue(0 <= criticality(task(1)) <= 1)

    def test_priority(self):
        s = composite(task(1), 96 * 1024**2, PROFILE.data['scheduler'])
        self.assertTrue(0 <= s <= 1)

class TestCache(unittest.TestCase):
    def test_way_partition(self):
        cache = PartitionedCache(16 * 8 * 64, 16, 12, 64, 1000)
        for i in range(12):
            cache.access(i * 8 * 64, Domain.P)
        for i in range(40):
            cache.access((i + 1000) * 8 * 64, Domain.E)
        for i in range(12):
            self.assertTrue(cache.access(i * 8 * 64, Domain.P, insert=False))
        self.assertTrue(cache.invariant())

    def test_bounded_memory(self):
        cache = PartitionedCache(16 * 8 * 64, 16, 12, 64, 10)
        for i in range(100):
            cache.access(i * 64, Domain.P)
        self.assertEqual(cache.size, 10)
        self.assertTrue(cache.invariant())

    def test_cache_latency_hit(self):
        c = CacheHierarchy(PROFILE)
        self.assertEqual(c.access(64, 0, Domain.P).level, 'dram')
        self.assertEqual(c.access(64, 0, Domain.P).level, 'l0')

class TestScheduling(unittest.TestCase):
    def test_classes(self):
        placements = Scheduler(PROFILE).assign([task(1), task(2, Instruction.TENSOR), task(3, Instruction.BACKGROUND)])
        by_id = {p.task_id: p.domain for p in placements}
        self.assertEqual(by_id[1], Domain.P)
        self.assertEqual(by_id[2], Domain.NPU)
        self.assertEqual(by_id[3], Domain.E)

    def test_determinism(self):
        a = Scheduler(PROFILE).assign([task(1), task(2)])
        b = Scheduler(PROFILE).assign([task(2), task(1)])
        self.assertEqual(a, b)

    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            Scheduler(PROFILE).assign([task(1), task(1)])

class TestFabric(unittest.TestCase):
    def test_zero_copy(self):
        fabric = Fabric(PROFILE)
        view, transfer = fabric.put(b'abc')
        self.assertIs(view.obj, fabric.arena)
        self.assertEqual(view.tobytes(), b'abc')
        self.assertGreater(transfer.latency_ns, 0)

    def test_bounds(self):
        with self.assertRaises(ValueError):
            Fabric(PROFILE).put(b'X' * (262145))

    def test_directory(self):
        fabric = Fabric(PROFILE)
        fabric.register(64, 1)
        self.assertEqual(fabric.lookup(64, 1), (True, .7))
        self.assertEqual(fabric.lookup(64, 2), (True, 2.1))
        self.assertEqual(fabric.lookup(128, 2), (False, 0.0))

class TestRecovery(unittest.TestCase):
    def test_recover(self):
        blob = checkpoint({'a': [1, 2, 3]})
        self.assertEqual(recover(blob), {'a': [1, 2, 3]})
        with self.assertRaises(ValueError):
            recover(blob.replace(b'1,2,3', b'1,2,4'))

    def test_breaker(self):
        c = CircuitBreaker(2, 10)
        c.record(0, False)
        c.record(1, False)
        self.assertFalse(c.allow(5))
        self.assertTrue(c.allow(11))
        c.record(11, True)
        self.assertEqual(c.state, 'closed')

    def test_jitter(self):
        self.assertEqual(retries(42, 10), retries(42, 10))
        self.assertNotEqual(retries(43, 10), retries(42, 10))

class TestIntegration(unittest.TestCase):
    def test_full_runtime(self):
        out = OmegaRuntime(PROFILE).run([task(1), task(2, Instruction.TENSOR)])
        self.assertTrue(all(out['invariants'].values()))
        self.assertEqual(out['tasks'], 2)
        self.assertEqual(sum(out['cache_hits'].values()), 8)

    def test_adapter_roundtrip(self):
        payload = encode([task(1)], 'x-01')
        req, tasks = decode(payload)
        self.assertEqual(req, 'x-01')
        self.assertEqual(tasks, [task(1)])
        self.assertEqual(idempotency_key(payload), idempotency_key(payload))

    def test_adapter_version_reject(self):
        payload = json.loads(encode([task(1)], 'x'))
        payload['version'] = 2
        with self.assertRaises(ValueError):
            decode(json.dumps(payload).encode())

    def test_twin_multi_seed(self):
        for seed in (0, 1, 42, 1337, 20261111):
            self.assertEqual(DeterministicTwin(seed).run(400), DeterministicTwin(seed).run(400))

    def test_fault_matrix(self):
        for nodes in (1, 3, 5, 16):
            out = DeterministicTwin(42, nodes).run(1000)
            self.assertEqual(out['successes'] + out['failures'] + out['rejected'], 1000)

if __name__ == '__main__':
    unittest.main()
