"""In-memory LRU cache with optional disk overflow placeholder."""
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Optional


class CacheManager:
    """
    Two-level image cache: LRU in RAM + placeholder for disk cache.

    Keys are typically (path_str, size_hint) tuples.
    Values are QImage instances or numpy arrays.
    """

    def __init__(self, max_ram_entries: int = 32, max_ram_mb: float = 256.0) -> None:
        self._max_entries = max_ram_entries
        self._max_bytes = int(max_ram_mb * 1024 * 1024)
        self._lru: OrderedDict[Any, Any] = OrderedDict()
        self._sizes: dict[Any, int] = {}
        self._current_bytes: int = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def get(self, key: Any) -> Optional[Any]:
        """Return cached value for *key*, or None on miss. Refreshes LRU order."""
        with self._lock:
            if key not in self._lru:
                return None
            self._lru.move_to_end(key)
            return self._lru[key]

    def put(self, key: Any, value: Any, size_bytes: int = 0) -> None:
        """Insert *value* under *key*. Evicts oldest entries as needed."""
        with self._lock:
            if key in self._lru:
                self._lru.move_to_end(key)
                old_size = self._sizes.get(key, 0)
                self._current_bytes -= old_size
            self._lru[key] = value
            self._sizes[key] = size_bytes
            self._current_bytes += size_bytes
            self._evict()

    def invalidate(self, key: Any) -> None:
        """Remove a specific entry."""
        with self._lock:
            if key in self._lru:
                self._current_bytes -= self._sizes.pop(key, 0)
                del self._lru[key]

    def clear(self) -> None:
        """Evict all entries."""
        with self._lock:
            self._lru.clear()
            self._sizes.clear()
            self._current_bytes = 0

    @property
    def entry_count(self) -> int:
        with self._lock:
            return len(self._lru)

    @property
    def used_bytes(self) -> int:
        with self._lock:
            return self._current_bytes

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _evict(self) -> None:
        while (len(self._lru) > self._max_entries
               or self._current_bytes > self._max_bytes):
            if not self._lru:
                break
            oldest_key, _ = self._lru.popitem(last=False)
            self._current_bytes -= self._sizes.pop(oldest_key, 0)

    # ------------------------------------------------------------------ #
    # Disk cache stub                                                      #
    # ------------------------------------------------------------------ #

    def get_from_disk(self, key: Any) -> Optional[Any]:
        """Placeholder: retrieve entry from disk cache. Not yet implemented."""
        return None

    def put_to_disk(self, key: Any, value: Any) -> None:
        """Placeholder: persist entry to disk cache. Not yet implemented."""
