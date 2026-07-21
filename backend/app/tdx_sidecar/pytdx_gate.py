"""Serialize pytdx HQ connections — concurrent connect/quote is unreliable."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

PYTDX_GATE = threading.RLock()


@contextmanager
def pytdx_slot(timeout: float = 2.5) -> Iterator[bool]:
    """Acquire pytdx gate with timeout. Yields True if acquired, False if busy."""
    got = PYTDX_GATE.acquire(timeout=timeout)
    try:
        yield got
    finally:
        if got:
            PYTDX_GATE.release()
