"""Regression and acceptance gates for real v3 CPU execution and cache protection."""
from __future__ import annotations
import os
from pathlib import Path
import tempfile
import unittest

from omega_x.cache import PartitionedCache
from omega_x.model import Domain, Instruction, Workload
from omega_x.native import NativeKernels
from omega_x.topology import detect_topology, classify_cpu, CPUDescriptor, PhysicalTopology
from omega_x.real_policy import PhysicalPlanner, RealPlan
from omega_x.executor import LocalExecutor, ExecutionRequest


class TestPartitionCap(unittest.TestCase):
    def test_e_streaming_cannot_evict_resident_p_lines_at_global_cap(self):
        cache = PartitionedCache(16384, 4, 3, 64, 8)
        p_addresses = [i*64 for i in range(6)]
        for addr in p_addresses:
            self.assertFalse(cache.access(addr, Domain.P))
        for i in range(1000):
            cache.access((i+10000)*64, Domain.E)
        self.assertTrue(all(cache.access(addr, Domain.P, insert=False) for addr in p_addresses))
        self.assertTrue(cache.invariant())
        self.assertLessEqual(cache.size, 8)

    def test_per_domain_quotas_follow_way_geometry(self):
        cache = PartitionedCache(16384, 4, 3, 64, 8)
        self.assertEqual(cache.quotas[Domain.P], 6)
        self.assertEqual(cache.quotas[Domain.E], 2)
        self.assertTrue(cache.invariant())

    def test_p_can_reclaim_from_e_when_global_limit_is_full(self):
        cache = PartitionedCache(16384, 4, 3, 64, 8)
        for i in range(8):
            cache.access((100+i)*64, Domain.E)
        for i in range(8):
            cache.access((10000+i)*64, Domain.P)
        self.assertTrue(all(cache.access((10000+i)*64, Domain.P, insert=False) for i in range(8)))
        for i in range(1000):
            cache.access((20000+i)*64, Domain.E)
        self.assertTrue(all(cache.access((10000+i)*64, Domain.P, insert=False) for i in range(8)))
        self.assertTrue(cache.invariant())

    def test_invalid_zero_capacity_is_rejected(self):
        with self.assertRaises(ValueError):
            PartitionedCache(16384, 4, 3, 64, 1)

    def test_probe_does_not_materialize_empty_cache_set(self):
        cache = PartitionedCache(16384, 4, 3, 64, 8)
        self.assertFalse(cache.access(32, Domain.P, insert=False))
        self.assertEqual(len(cache.entries), 0)


class TestPhysicalTopology(unittest.TestCase):
    def test_real_cpu_ids_are_subset_of_allowed(self):
        topo = detect_topology()
        self.assertEqual({c.cpu_id for c in topo.cpus}, set(os.sched_getaffinity(0)))
        self.assertTrue(all(c.kind in ('P', 'E', 'UNCLASSIFIED') for c in topo.cpus))

    def test_classify_prefers_explicit_linux_core_type(self):
        self.assertEqual(classify_cpu(core_type=2, capacity=None), 'P')
        self.assertEqual(classify_cpu(core_type=1, capacity=None), 'E')
        self.assertEqual(classify_cpu(core_type=7, capacity=None), 'UNCLASSIFIED')
        self.assertEqual(classify_cpu(core_type=None, capacity=1024), 'UNCLASSIFIED')

    def test_mock_hybrid_never_sends_priority_vector_to_efficiency_core(self):
        topo = PhysicalTopology((CPUDescriptor(3,'P',0), CPUDescriptor(6,'E',0), CPUDescriptor(8,'P',1)))
        policy = PhysicalPlanner(topo)
        high = Workload(1,'vector',Instruction.VECTOR,1000,1024)
        batch = Workload(2,'background',Instruction.BACKGROUND,1000,512)
        scheduled = policy.plan([batch, high])
        self.assertEqual(scheduled[0].cpu,6)
        self.assertIn(scheduled[1].cpu,(3,8))
        self.assertTrue(scheduled[1].verified_topology)

    def test_unknown_or_uniform_topology_fallback_does_not_invent_p_e(self):
        topo = PhysicalTopology((CPUDescriptor(100,'UNCLASSIFIED',0),CPUDescriptor(101,'UNCLASSIFIED',0)))
        plan = PhysicalPlanner(topo).plan([Workload(7,'x',Instruction.VECTOR,1,64)])
        self.assertEqual(plan[0].cpu,100)
        self.assertFalse(plan[0].verified_topology)

    def test_duplicate_task_ids_rejected(self):
        topo = PhysicalTopology((CPUDescriptor(0,'UNCLASSIFIED',0),))
        work = Workload(1,'x',Instruction.VECTOR,3,64)
        with self.assertRaises(ValueError):
            PhysicalPlanner(topo).plan([work,work])


class TestActualGEMM(unittest.TestCase):
    def test_int8_gemm_agrees_with_integer_oracle(self):
        engine = NativeKernels()
        a = [[-128, 127, -1], [100, 0, -100]]
        b = [[3, -2], [-7, 11], [80, 90]]
        actual = engine.matmul_int8(a,b)
        expected = [[sum(a[i][k]*b[k][j] for k in range(3)) for j in range(2)] for i in range(2)]
        self.assertEqual(actual,expected)

    def test_int8_gemm_checks_bounds_shapes_and_type(self):
        engine = NativeKernels()
        for a,b in (([[1,2]],[[1]]), ([[200]],[[1]]), ([[True]],[[1]]), ([[1]],[[1.2]]), ([],[[1]])):
            with self.assertRaises(ValueError):
                engine.matmul_int8(a,b)

    def test_int8_accumulation_preserves_exact_signed_products(self):
        engine = NativeKernels()
        n = 256
        a = [[-128]*n]
        b = [[-128] for _ in range(n)]
        self.assertEqual(engine.matmul_int8(a,b), [[128*128*n]])


class TestPolicyExecution(unittest.TestCase):
    def test_batch_exec_uses_only_allowed_cpus_and_real_digests(self):
        from hashlib import sha256
        from omega_x.real_policy import PhysicalExecutor
        result = PhysicalExecutor().run([ExecutionRequest('sha256', 768), ExecutionRequest('sha256', 769)], timeout_s=10, workers=2)
        allowed = os.sched_getaffinity(0)
        self.assertEqual(len(result),2)
        for receipt in result:
            self.assertIn(receipt['cpu_affinity'],allowed)
            self.assertEqual(receipt['status'],'ok')
            self.assertEqual(len(receipt['digest']),64)


if __name__=='__main__':
    unittest.main()
