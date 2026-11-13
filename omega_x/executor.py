"""Bounded real Linux process executor with cpuset enforcement and hard deadlines."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import multiprocessing
import os
import time
from .host import detect_host, select_cpu
from .native import NativeKernels


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    kind: str
    size: int
    cpu: int | None = None

    def __post_init__(self):
        if self.kind not in ('sha256', 'saxpy', 'memory'):
            raise ValueError('unapproved execution operation')
        if isinstance(self.size, bool) or not isinstance(self.size, int) or not 1 <= self.size <= 16 * 1024 * 1024:
            raise ValueError('work size outside [1,16MiB]')
        if self.cpu is not None and (isinstance(self.cpu, bool) or not isinstance(self.cpu, int) or self.cpu < 0):
            raise ValueError('invalid CPU id')


def _worker(request: ExecutionRequest, cpu: int, channel) -> None:
    try:
        os.sched_setaffinity(0, {cpu})
        if os.sched_getaffinity(0) != {cpu}:
            raise RuntimeError('affinity mismatch')
        started = time.perf_counter_ns()
        if request.kind == 'sha256':
            data = bytes(range(256)) * (request.size // 256) + bytes(range(request.size % 256))
            digest = hashlib.sha256(data).hexdigest()
            extra = {'digest': digest}
        elif request.kind == 'saxpy':
            n = min(request.size, 1_000_000)
            x = [float(i % 97) for i in range(n)]
            y = [float(i % 17) for i in range(n)]
            kernel = NativeKernels()
            result = kernel.saxpy(x, y, .125)
            extra = {'result_sha256': hashlib.sha256(__import__('array').array('f', result).tobytes()).hexdigest(),
                     'native_features': kernel.features(), 'elements': n}
        else:
            data = bytearray(request.size)
            for i in range(0, len(data), 4096):
                data[i] = (i // 4096) & 255
            extra = {'checksum': sum(data)}
        elapsed = max(1, time.perf_counter_ns() - started)
        channel.send({'status': 'ok', 'kind': request.kind, 'cpu_affinity': cpu, 'wall_ns': elapsed, **extra})
    except BaseException as exc:
        try:
            channel.send({'status': 'error', 'type': type(exc).__name__, 'message': str(exc)[:256]})
        except (OSError, BrokenPipeError):
            return
    finally:
        channel.close()


class LocalExecutor:
    def __init__(self):
        self.host = detect_host()

    def run_one(self, request: ExecutionRequest, timeout_s: float = 10.0) -> dict:
        if not 0 < timeout_s <= 120:
            raise ValueError('timeout must be in (0,120]')
        cpu = select_cpu(self.host, request.cpu if request.cpu is not None else self.host.allowed_cpus[0])
        ctx = multiprocessing.get_context('spawn')
        receiver, sender = ctx.Pipe(duplex=False)
        process = ctx.Process(target=_worker, args=(request, cpu, sender))
        try:
            process.start()
            sender.close()
            if not receiver.poll(timeout_s):
                process.terminate()
                process.join(timeout=1)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=1)
                raise TimeoutError('worker exceeded hard deadline')
            try:
                result = receiver.recv()
            except EOFError as exc:
                raise RuntimeError('worker terminated without a result') from exc
            process.join(timeout=1)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
            if result.get('status') != 'ok':
                raise RuntimeError(f"worker error: {result.get('type')} {result.get('message')}")
            if process.exitcode != 0:
                raise RuntimeError('worker abnormal exit')
            return result
        finally:
            receiver.close()
            sender.close()
            if process.is_alive():
                process.kill()
                process.join(timeout=1)

    def run_batch(self, requests: list[ExecutionRequest], timeout_s: float = 10.0, workers: int = 2) -> list[dict]:
        if not 1 <= len(requests) <= 64 or not 1 <= workers <= min(16, len(self.host.allowed_cpus)):
            raise ValueError('invalid bounded batch')
        assigned = [ExecutionRequest(r.kind, r.size,
                                    r.cpu if r.cpu is not None else self.host.allowed_cpus[i % len(self.host.allowed_cpus)])
                    for i, r in enumerate(requests)]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(lambda r: self.run_one(r, timeout_s), assigned))
