"""Acceptance tests for real host execution, native SIMD, IPC and durable ledger."""
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import threading
import time
import unittest

from omega_x.host import detect_host, select_cpu
from omega_x.ipc import SharedArena
from omega_x.native import NativeKernels, NativeQueue
from omega_x.executor import LocalExecutor, ExecutionRequest
from omega_x.ledger import EvidenceLedger, LedgerConflict, LedgerCorrupt

ROOT = Path(__file__).resolve().parents[1]


def child_read(fd: int, capacity: int, conn):
    try:
        with SharedArena.attach(fd, capacity) as arena:
            conn.send(arena.read().decode('utf-8'))
    except Exception as exc:
        conn.send(repr(exc))
    finally:
        conn.close()


class TestHost(unittest.TestCase):
    def test_detect_host_is_actual_not_virtual_topology(self):
        host = detect_host()
        self.assertEqual(set(host.allowed_cpus), set(os.sched_getaffinity(0)))
        self.assertTrue(host.architecture)
        self.assertGreaterEqual(len(host.allowed_cpus), 1)
        self.assertIn(host.avx512, (True, False))
        self.assertEqual(select_cpu(host, host.allowed_cpus[-1]), host.allowed_cpus[-1])

    def test_disallowed_affinity_is_rejected(self):
        host = detect_host()
        with self.assertRaises(ValueError):
            select_cpu(host, max(host.allowed_cpus) + 10000)


class TestNative(unittest.TestCase):
    def test_native_saxpy_matches_scalar_for_unaligned_length(self):
        native = NativeKernels()
        self.assertTrue(native.available)
        xs = [float(i) / 7 for i in range(1031)]
        ys = [float(i % 11) for i in range(1031)]
        actual = native.saxpy(xs, ys, 0.125)
        scalar = native.saxpy(xs, ys, 0.125, mode='scalar')
        for a, b in zip(actual, scalar):
            self.assertAlmostEqual(a, b, delta=0.0002)
        self.assertEqual(len(actual), 1031)

    def test_incompatible_binary_falls_back_to_scalar(self):
        from unittest.mock import patch
        from omega_x import native
        fake = ROOT / 'results/tmp/not-a-library.so'
        fake.parent.mkdir(parents=True, exist_ok=True)
        fake.write_bytes(b'invalid ELF')
        with patch.object(native, 'LIBRARY', fake):
            kernels = native.NativeKernels()
            self.assertFalse(kernels.available)
            self.assertEqual(kernels.saxpy([2.0], [3.0], 2.0), [7.0])

    def test_native_rejects_bad_shape_and_nan(self):
        native = NativeKernels()
        with self.assertRaises(ValueError):
            native.saxpy([1], [1, 2], 1)
        with self.assertRaises(ValueError):
            native.saxpy([float('nan')], [1], 1)

    def test_spsc_native_queue_order_and_backpressure(self):
        with NativeQueue(8) as queue:
            self.assertEqual([queue.push(i) for i in range(8)], [True] * 8)
            self.assertFalse(queue.push(99))
            self.assertEqual([queue.pop() for _ in range(8)], list(range(8)))
            self.assertIsNone(queue.pop())

    def test_spsc_threaded_10000_items(self):
        with NativeQueue(64) as queue:
            n = 10000
            received = []
            def producer():
                for value in range(n):
                    while not queue.push(value):
                        time.sleep(0)
            def consumer():
                while len(received) < n:
                    value = queue.pop()
                    if value is not None:
                        received.append(value)
            a = threading.Thread(target=producer)
            b = threading.Thread(target=consumer)
            a.start(); b.start(); a.join(timeout=10); b.join(timeout=10)
            self.assertFalse(a.is_alive() or b.is_alive())
            self.assertEqual(received, list(range(n)))


class TestIPC(unittest.TestCase):
    def test_memfd_zero_copy_read_cross_process_and_integrity(self):
        with SharedArena.create(4096) as arena:
            arena.write(b'omega-x-ipc')
            self.assertEqual(arena.read(), b'omega-x-ipc')
            self.assertEqual(bytes(arena.view()), b'omega-x-ipc')
            ctx = multiprocessing.get_context('fork')
            parent, child = ctx.Pipe(duplex=False)
            process = ctx.Process(target=child_read, args=(arena.fd, 4096, child))
            process.start(); child.close()
            self.assertEqual(parent.recv(), 'omega-x-ipc')
            process.join(timeout=3)
            self.assertEqual(process.exitcode, 0)

    def test_memfd_capacity_and_tamper_detection(self):
        with SharedArena.create(128) as arena:
            with self.assertRaises(ValueError):
                arena.write(b'a' * 128)
            arena.write(b'payload')
            arena._mapping[40] = ord('X')
            with self.assertRaises(ValueError):
                arena.read()


class TestExecution(unittest.TestCase):
    def test_actual_cpu_hash_worker_and_affinity(self):
        executor = LocalExecutor()
        result = executor.run_one(ExecutionRequest('sha256', 256 * 1024, cpu=detect_host().allowed_cpus[0]), timeout_s=8)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['kind'], 'sha256')
        self.assertEqual(result['cpu_affinity'], detect_host().allowed_cpus[0])
        self.assertEqual(len(result['digest']), 64)
        self.assertGreater(result['wall_ns'], 0)

    def test_execution_rejects_unbounded_work_and_timeout(self):
        with self.assertRaises(ValueError):
            ExecutionRequest('sha256', 1 << 31)
        with self.assertRaises(ValueError):
            ExecutionRequest('shell', 4)
        with self.assertRaises(ValueError):
            LocalExecutor().run_one(ExecutionRequest('sha256', 128), timeout_s=0)


class TestLedger(unittest.TestCase):
    def test_idempotent_transaction_and_chain_replay(self):
        db = ROOT / 'results/tmp/ledger_test.sqlite3'
        for suffix in ('', '-wal', '-shm'):
            (ROOT / ('results/tmp/ledger_test.sqlite3' + suffix)).unlink(missing_ok=True)
        with EvidenceLedger(db) as ledger:
            one = ledger.append('r1', b'hello', {'answer': 1})
            self.assertEqual(one, ledger.append('r1', b'hello', {'answer': 1}))
            with self.assertRaises(LedgerConflict):
                ledger.append('r1', b'changed', {'answer': 1})
            ledger.append('r2', b'world', {'answer': 2})
            self.assertEqual(ledger.verify()['records'], 2)
            ledger._db.execute('UPDATE evidence SET result_json=? WHERE seq=1', ('{"answer":99}',))
            with self.assertRaises(LedgerCorrupt):
                ledger.verify()


if __name__ == '__main__':
    unittest.main()
