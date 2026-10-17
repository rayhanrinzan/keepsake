"""In-process pub/sub bus. Slow subscribers lose their oldest messages."""
from __future__ import annotations

import queue
import threading
import time


class Bus:
    def __init__(self) -> None:
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> "queue.Queue[dict]":
        q: queue.Queue = queue.Queue(maxsize=200)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: "queue.Queue[dict]") -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)

    def publish(self, type: str, **payload) -> None:
        msg = {"type": type, "ts": time.time(), **payload}
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            while True:
                try:
                    q.put_nowait(msg)
                    break
                except queue.Full:
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        pass
