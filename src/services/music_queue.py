"""Bounded, testable in-memory queue primitives for music playback."""

from __future__ import annotations

from collections import deque
import random
from typing import Generic, Iterable, Iterator, TypeVar


TrackT = TypeVar("TrackT")


class QueueFullError(ValueError):
    """Raised when an operation would exceed the configured queue capacity."""

    def __init__(self, max_size: int, requested: int, available: int):
        self.max_size = max_size
        self.requested = requested
        self.available = available
        super().__init__(
            f"Queue capacity {max_size} exceeded: requested {requested}, available {available}"
        )


class MusicQueue(Generic[TrackT]):
    def __init__(self, max_size: int = 200):
        if max_size < 1:
            raise ValueError("max_size must be positive")
        self.max_size = max_size
        self._items: deque[TrackT] = deque()

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        return bool(self._items)

    def __iter__(self) -> Iterator[TrackT]:
        return iter(self._items)

    @property
    def available(self) -> int:
        return self.max_size - len(self._items)

    def append(self, item: TrackT) -> int:
        self.extend([item])
        return len(self._items)

    def appendleft(self, item: TrackT) -> None:
        self._ensure_capacity(1)
        self._items.appendleft(item)

    def extend(self, items: Iterable[TrackT]) -> int:
        batch = list(items)
        self._ensure_capacity(len(batch))
        first_position = len(self._items) + 1
        self._items.extend(batch)
        return first_position

    def popleft(self) -> TrackT:
        return self._items.popleft()

    def remove(self, position: int) -> TrackT:
        if not 1 <= position <= len(self._items):
            raise IndexError("Queue position is out of range")
        items = list(self._items)
        removed = items.pop(position - 1)
        self._items = deque(items)
        return removed

    def shuffle(self, randomizer: random.Random | None = None) -> None:
        items = list(self._items)
        (randomizer or random.SystemRandom()).shuffle(items)
        self._items = deque(items)

    def clear(self) -> int:
        count = len(self._items)
        self._items.clear()
        return count

    def snapshot(self, limit: int | None = None) -> list[TrackT]:
        items = list(self._items)
        return items if limit is None else items[:limit]

    def _ensure_capacity(self, requested: int) -> None:
        if requested > self.available:
            raise QueueFullError(self.max_size, requested, self.available)
