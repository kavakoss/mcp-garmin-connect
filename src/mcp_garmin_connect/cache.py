from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class _Entry(Generic[T]):
    expires_at: float
    value: T


class TTLCache:
    def __init__(self, ttl_seconds: int) -> None:
        self.ttl_seconds = ttl_seconds
        self._entries: dict[str, _Entry[object]] = {}
        self._lock = RLock()

    def get_or_set(self, key: str, factory: Callable[[], T]) -> T:
        now = time.time()
        with self._lock:
            entry = self._entries.get(key)
            if entry and entry.expires_at > now:
                return entry.value  # type: ignore[return-value]

        value = factory()
        with self._lock:
            self._entries[key] = _Entry(expires_at=now + self.ttl_seconds, value=value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
