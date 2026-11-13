"""ctypes wrapper for checked SIMD dispatch and native SPSC queue."""
from __future__ import annotations
from array import array
import ctypes
import math
from pathlib import Path

LIBRARY = Path(__file__).resolve().parents[1] / 'native' / 'libomegax.so'


def _load():
    if not LIBRARY.is_file():
        return None
    try:
        lib = ctypes.CDLL(str(LIBRARY))
    except OSError:
        return None
    lib.ox_cpu_features.argtypes = []
    lib.ox_cpu_features.restype = ctypes.c_int
    ptr = ctypes.POINTER(ctypes.c_float)
    lib.ox_saxpy.argtypes = [ptr, ptr, ptr, ctypes.c_size_t, ctypes.c_float, ctypes.c_int]
    lib.ox_saxpy.restype = ctypes.c_int
    lib.ox_queue_create.argtypes = [ctypes.c_size_t]
    lib.ox_queue_create.restype = ctypes.c_void_p
    lib.ox_queue_destroy.argtypes = [ctypes.c_void_p]
    lib.ox_queue_destroy.restype = None
    lib.ox_queue_push.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
    lib.ox_queue_push.restype = ctypes.c_int
    lib.ox_queue_pop.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint64)]
    lib.ox_queue_pop.restype = ctypes.c_int
    lib.ox_queue_size.argtypes = [ctypes.c_void_p]
    lib.ox_queue_size.restype = ctypes.c_size_t
    lib.ox_matmul_i8.argtypes = [ctypes.POINTER(ctypes.c_int8), ctypes.POINTER(ctypes.c_int8),
                                ctypes.POINTER(ctypes.c_int64), ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t]
    lib.ox_matmul_i8.restype = ctypes.c_int
    return lib


class NativeKernels:
    def __init__(self):
        self._lib = _load()

    @property
    def available(self) -> bool:
        return self._lib is not None

    def features(self) -> tuple[str, ...]:
        if not self._lib:
            return ('scalar',)
        mask = self._lib.ox_cpu_features()
        return ('scalar',) + (('avx2',) if mask & 1 else ()) + (('avx512',) if mask & 2 else ())

    def saxpy(self, x, y, factor: float, mode: str = 'auto') -> list[float]:
        if mode not in ('auto', 'scalar', 'avx2', 'avx512'):
            raise ValueError('unknown SIMD mode')
        if len(x) != len(y) or len(x) > 2_000_000:
            raise ValueError('invalid vector lengths')
        if not math.isfinite(factor):
            raise ValueError('invalid multiplier')
        if any(not math.isfinite(v) for v in x) or any(not math.isfinite(v) for v in y):
            raise ValueError('nonfinite input')
        count = len(x)
        if not self._lib:
            if mode not in ('auto', 'scalar'):
                raise RuntimeError('native SIMD library unavailable')
            return [float(factor * a + b) for a, b in zip(x, y)]
        ax = (ctypes.c_float * count)(*x)
        ay = (ctypes.c_float * count)(*y)
        dst = (ctypes.c_float * count)()
        code = self._lib.ox_saxpy(ax, ay, dst, count, factor,
                                  {'auto': 0, 'scalar': 1, 'avx2': 2, 'avx512': 3}[mode])
        if code < 0:
            raise RuntimeError('SIMD mode unsupported or invalid native input')
        return list(dst)

    def matmul_int8(self, left, right) -> list[list[int]]:
        """Exact signed INT8 matrix multiplication using checked INT64 CPU accumulation.

        Only CPU instruction paths are employed; NPU availability is not implied.
        Rectangular 2-D arrays are bounded to <=256 per dimension.
        """
        if (not isinstance(left, (list, tuple)) or not isinstance(right, (list, tuple))
                or not left or not right or not isinstance(left[0], (list, tuple))
                or not isinstance(right[0], (list, tuple))):
            raise ValueError('matrices must be non-empty 2D sequences')
        m = len(left)
        k = len(left[0])
        kb = len(right)
        n = len(right[0])
        if not 1 <= min(m, n, k) or max(m, n, k) > 256 or kb != k:
            raise ValueError('incompatible or oversized INT8 GEMM dimensions')
        for matrix, cols in ((left, k), (right, n)):
            for row in matrix:
                if not isinstance(row, (list, tuple)) or len(row) != cols:
                    raise ValueError('ragged INT8 matrix')
                if any(type(value) is not int or not -128 <= value <= 127 for value in row):
                    raise ValueError('INT8 element outside [-128,127]')
        aa = [v for row in left for v in row]
        bb = [v for row in right for v in row]
        if self._lib is None:
            return [[sum(left[i][p] * right[p][j] for p in range(k))
                     for j in range(n)] for i in range(m)]
        a = (ctypes.c_int8 * (m*k))(*aa)
        b = (ctypes.c_int8 * (k*n))(*bb)
        out = (ctypes.c_int64 * (m*n))()
        status = self._lib.ox_matmul_i8(a,b,out,m,k,n)
        if status != 0:
            raise RuntimeError('native INT8 GEMM rejected input')
        return [[out[i*n+j] for j in range(n)] for i in range(m)]


class NativeQueue:
    """SPSC: exactly one producer and one consumer; no concurrent close."""
    def __init__(self, capacity: int):
        self._lib = _load()
        if not self._lib:
            raise RuntimeError('native queue requires compiled C11 library')
        self._handle = self._lib.ox_queue_create(capacity)
        if not self._handle:
            raise ValueError('queue capacity must be power of two in [2, 2^20]')

    def push(self, value: int) -> bool:
        if self._handle is None:
            raise RuntimeError('queue closed')
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 2**64:
            raise ValueError('queue item must be unsigned 64-bit integer')
        return self._lib.ox_queue_push(self._handle, value) == 1

    def pop(self) -> int | None:
        if self._handle is None:
            raise RuntimeError('queue closed')
        value = ctypes.c_uint64()
        result = self._lib.ox_queue_pop(self._handle, ctypes.byref(value))
        return value.value if result == 1 else None

    def size(self) -> int:
        if self._handle is None:
            raise RuntimeError('queue closed')
        return self._lib.ox_queue_size(self._handle)

    def close(self):
        if self._handle is not None:
            self._lib.ox_queue_destroy(self._handle)
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
