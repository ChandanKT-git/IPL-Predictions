"""In-process TTL cache for Cricbuzz responses and resolver-derived payloads.

Implements the ``Cache_Layer`` component described in the
``real-data-cricbuzz-integration`` design document. The cache is a plain
Python ``dict`` keyed by string, mapping to ``(value, expires_at)`` pairs
where ``expires_at`` is a monotonic timestamp produced by the injected
``clock`` callable (defaults to :func:`time.monotonic`).

Design notes:

* No serialization, no eviction policy beyond TTL, no max size.
* Entries are removed lazily on access (``get``) once expired.
* The cache lives for the lifetime of the host process and starts empty on
  every boot (Requirement 6.7).
* ``set`` with ``ttl <= 0`` is a no-op so the admin invalidation flow can
  call ``set(key, None, ttl=0)`` without polluting the cache.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Tuple


class CacheLayer:
    """Thread-unsafe in-process TTL cache.

    Parameters
    ----------
    clock:
        Callable returning a monotonic float timestamp in seconds. Injectable
        so tests can drive a virtual clock; defaults to :func:`time.monotonic`.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._store: dict[str, Tuple[Any, float]] = {}

    def get(self, key: str) -> Tuple[Any, bool]:
        """Return ``(value, True)`` for an unexpired entry, else ``(None, False)``.

        Expired entries are deleted lazily on access.
        """
        entry = self._store.get(key)
        if entry is None:
            return (None, False)
        value, expires_at = entry
        if self._clock() >= expires_at:
            # Lazy expiry: evict and report a miss.
            del self._store[key]
            return (None, False)
        return (value, True)

    def set(self, key: str, value: Any, ttl: int) -> None:
        """Store ``value`` under ``key`` with a TTL of ``ttl`` seconds.

        ``ttl <= 0`` is a no-op (used by the admin invalidation flow). If a
        prior entry exists for ``key`` it is invalidated as well so the next
        ``get`` reports a miss.
        """
        if ttl <= 0:
            # Treat non-positive TTLs as an explicit "do not store" signal.
            # Also drop any prior entry so the caller observes a clean miss.
            self._store.pop(key, None)
            return
        expires_at = self._clock() + ttl
        self._store[key] = (value, expires_at)

    def clear(self) -> int:
        """Remove every entry. Return the number of entries removed."""
        n = len(self._store)
        self._store.clear()
        return n

    def keys_matching(self, prefix: str) -> list[str]:
        """Return unexpired keys whose names start with ``prefix``.

        Expired entries encountered during the scan are evicted lazily so the
        result reflects the live cache state.
        """
        now = self._clock()
        expired: list[str] = []
        matches: list[str] = []
        for key, (_value, expires_at) in self._store.items():
            if now >= expires_at:
                expired.append(key)
                continue
            if key.startswith(prefix):
                matches.append(key)
        for key in expired:
            self._store.pop(key, None)
        return matches
