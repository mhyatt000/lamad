"""OCCT writes diagnostics straight to file descriptor 1, bypassing sys.stdout.

That corrupts any "stdout is JSON" contract. Redirect fd 1 -> fd 2 around
kernel calls so the noise lands on stderr where it belongs.
"""
import ctypes
import os
import sys
from contextlib import contextmanager

try:
    _libc = ctypes.CDLL(None)
except OSError:  # pragma: no cover - no C runtime handle (unusual platforms)
    _libc = None


def _flush_c_stdio():
    """Flush C/C++ stdio buffers (OCCT prints via std::cout).

    When stdout is a pipe the C buffer is only flushed at exit, which would
    land kernel noise on the real stdout after fd 1 has been restored.
    """
    if _libc is not None:
        try:
            _libc.fflush(None)
        except Exception:  # pragma: no cover
            pass


@contextmanager
def quiet_kernel():
    sys.stdout.flush()
    _flush_c_stdio()
    saved = os.dup(1)
    try:
        os.dup2(2, 1)
        yield
    finally:
        _flush_c_stdio()
        os.dup2(saved, 1)
        os.close(saved)
