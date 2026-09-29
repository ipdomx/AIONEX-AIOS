"""C5E8 single-use random volume key in locked, non-dumpable anonymous memory.

No key bytes are converted into Python bytes/str, returned, logged, placed in
argv/environment, or written to a file. The callback accepts a native pointer
only while the private mapping is alive. The native crypto library and kernel
have their own copies; this class does not attest those copies or protect a live
privileged process from root. This is not persistent key custody or boot logic.
"""
from __future__ import annotations

import ctypes
import errno
import mmap
import os
from collections.abc import Callable
from typing import Self

KEY_BYTES = 64


class VolatileKeyRejected(RuntimeError):
    """Key creation must not proceed without its memory protections."""


class LockedKey:
    """Protect memory before requesting entropy, then wipe before unlocking."""
    def __init__(self) -> None:
        self._page: mmap.mmap | None = None
        self._locked = False
        self._used = False
        self._address = 0
        self._pid = os.getpid()
        self._lib = ctypes.CDLL(None, use_errno=True)
        self._lib.mlock.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        self._lib.mlock.restype = ctypes.c_int
        self._lib.munlock.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        self._lib.munlock.restype = ctypes.c_int
        self._lib.getrandom.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint]
        self._lib.getrandom.restype = ctypes.c_ssize_t
        self._size = os.sysconf("SC_PAGE_SIZE")
        if self._size != 4096:
            raise VolatileKeyRejected("Only the reviewed page profile is accepted")
        try:
            self._page = mmap.mmap(-1, self._size, flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS,
                                   prot=mmap.PROT_READ | mmap.PROT_WRITE)
            self._address = ctypes.addressof(ctypes.c_char.from_buffer(self._page))
            if self._lib.mlock(self._address, self._size) != 0:
                raise VolatileKeyRejected("Memory locking failed; no entropy requested")
            self._locked = True
            self._page.madvise(mmap.MADV_DONTDUMP)
            self._page.madvise(mmap.MADV_DONTFORK)
            position = 0
            while position < KEY_BYTES:
                count = self._lib.getrandom(self._address + position, KEY_BYTES-position, 0)
                if count < 0 and ctypes.get_errno() == errno.EINTR:
                    continue
                if count <= 0 or count > KEY_BYTES-position:
                    raise VolatileKeyRejected("Complete kernel entropy unavailable")
                position += count
        except BaseException:
            self.close()
            raise

    def use(self, callback: Callable[[ctypes.c_void_p, int], None]) -> None:
        if os.getpid() != self._pid or self._page is None or not self._locked or self._used:
            raise VolatileKeyRejected("Key is closed, inherited or already used")
        self._used = True
        callback(ctypes.c_void_p(self._address), KEY_BYTES)

    def close(self) -> None:
        if self._page is None:
            return
        if os.getpid() != self._pid:
            # MADV_DONTFORK removes this region from the child; touching the
            # inherited address would be invalid. Never expose it in a child.
            self._page = None
            self._address = 0
            self._locked = False
            return
        ctypes.memset(self._address, 0, self._size)
        if self._locked:
            self._lib.munlock(self._address, self._size)
        self._locked = False
        self._page.close()
        self._page = None
        self._address = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
