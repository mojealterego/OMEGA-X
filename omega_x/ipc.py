"""Real Linux memfd/mmap shared arena, fixed-size SHA-256-framed IPC and zero-copy views."""
from __future__ import annotations
import hashlib
import mmap
import os
import struct
import fcntl

_HEADER = struct.Struct('<4sIQ32s')
_MAGIC = b'OXIP'
_VERSION = 1


class SharedArena:
    def __init__(self, fd: int, capacity: int):
        if not isinstance(capacity, int) or not 64 <= capacity <= 64 * 1024 * 1024:
            raise ValueError('arena capacity outside [64B,64MiB]')
        if os.fstat(fd).st_size != capacity:
            raise ValueError('arena file size mismatch')
        self.fd = fd
        self.capacity = capacity
        self._mapping = mmap.mmap(fd, capacity, access=mmap.ACCESS_WRITE)
        self._closed = False

    @classmethod
    def create(cls, capacity: int) -> 'SharedArena':
        if not hasattr(os, 'memfd_create'):
            raise RuntimeError('memfd requires Linux')
        if not isinstance(capacity, int) or not 64 <= capacity <= 64 * 1024 * 1024:
            raise ValueError('invalid arena capacity')
        fd = os.memfd_create('omega-x-arena', os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
        try:
            os.ftruncate(fd, capacity)
            fcntl.fcntl(fd, fcntl.F_ADD_SEALS, fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW)
            return cls(fd, capacity)
        except BaseException:
            os.close(fd)
            raise

    @classmethod
    def attach(cls, fd: int, capacity: int) -> 'SharedArena':
        duplicate = os.dup(fd)
        try:
            return cls(duplicate, capacity)
        except BaseException:
            os.close(duplicate)
            raise

    def _ensure_open(self):
        if self._closed:
            raise RuntimeError('arena closed')

    def write(self, payload: bytes) -> None:
        self._ensure_open()
        if not isinstance(payload, (bytes, bytearray, memoryview)):
            raise ValueError('payload must be bytes-like')
        if not 0 < len(payload) <= self.capacity - _HEADER.size:
            raise ValueError('payload exceeds bounded arena')
        digest = hashlib.sha256(payload).digest()
        self._mapping[_HEADER.size:_HEADER.size + len(payload)] = payload
        self._mapping[:_HEADER.size] = _HEADER.pack(_MAGIC, _VERSION, len(payload), digest)

    def _validated_length(self) -> int:
        self._ensure_open()
        magic, version, n, digest = _HEADER.unpack(self._mapping[:_HEADER.size])
        if magic != _MAGIC or version != _VERSION or not 0 < n <= self.capacity - _HEADER.size:
            raise ValueError('invalid shared frame header')
        actual = hashlib.sha256(self._mapping[_HEADER.size:_HEADER.size + n]).digest()
        if actual != digest:
            raise ValueError('shared frame digest mismatch')
        return n

    def read(self) -> bytes:
        n = self._validated_length()
        return self._mapping[_HEADER.size:_HEADER.size + n]

    def view(self) -> memoryview:
        n = self._validated_length()
        return memoryview(self._mapping)[_HEADER.size:_HEADER.size + n]

    def close(self):
        if not self._closed:
            self._mapping.close()
            os.close(self.fd)
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
