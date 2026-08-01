from __future__ import annotations

import json
import queue
import threading
from dataclasses import dataclass
from typing import Any, Iterator

from ..constants import SCHEMA_VERSION

TERMINAL = ("review_complete", "error", "superseded")
IDLE_TIMEOUT_SECONDS = 600


@dataclass(frozen=True)
class Event:
    name: str
    payload: dict[str, Any]
    seq: int = 0

    def line(self) -> str:
        return json.dumps(
            {"event": self.name, "schema_version": SCHEMA_VERSION, "seq": self.seq, **self.payload}
        )


class EventStream:
    """Fan-out of pipeline progress: buffered for replay, live for subscribers.

    A subscriber that attaches before the review starts, midway through, or
    after it finished all see the same sequence.
    """

    def __init__(self) -> None:
        self.history: list[Event] = []
        self.subscribers: list[queue.Queue] = []
        self.lock = threading.Lock()
        self.closed = False
        self.counter = 0

    def emit(self, name: str, **payload: Any) -> None:
        with self.lock:
            self.counter += 1
            event = Event(name, payload, self.counter)
            self.history.append(event)
            if name in TERMINAL:
                self.closed = True
            subscribers = list(self.subscribers)
        for subscriber in subscribers:
            subscriber.put(event)

    def restart(self) -> None:
        """Reuse this stream for a re-review, closing out readers of the old run."""
        with self.lock:
            if not self.history:
                return
            self.counter += 1
            farewell = Event(
                "superseded", {"message": "a newer review replaced this one"}, self.counter
            )
            subscribers = list(self.subscribers)
            self.history.clear()
            self.closed = False
        for subscriber in subscribers:
            subscriber.put(farewell)

    def subscribe(self, idle_timeout: float = IDLE_TIMEOUT_SECONDS) -> Iterator[Event]:
        channel: queue.Queue = queue.Queue()
        with self.lock:
            replay = list(self.history)
            finished = self.closed
            self.subscribers.append(channel)
        delivered = replay[-1].seq if replay else 0
        try:
            for event in replay:
                yield event
            if finished:
                return
            while True:
                try:
                    event = channel.get(timeout=idle_timeout)
                except queue.Empty:
                    yield Event("error", {"message": "stream idle timeout"}, delivered + 1)
                    return
                if event.seq <= delivered:
                    continue  # already sent during replay
                delivered = event.seq
                yield event
                if event.name in TERMINAL:
                    return
        finally:
            with self.lock:
                if channel in self.subscribers:
                    self.subscribers.remove(channel)


class EventRegistry:
    """One stream per review, kept around so a late reader still sees the run."""

    def __init__(self, keep: int = 64):
        self.streams: dict[str, EventStream] = {}
        self.order: list[str] = []
        self.keep = keep
        self.lock = threading.Lock()

    def stream_for(self, review_id: str) -> EventStream:
        with self.lock:
            stream = self.streams.get(review_id)
            if stream is None:
                stream = EventStream()
                self.streams[review_id] = stream
                self.order.append(review_id)
                while len(self.order) > self.keep:
                    self.streams.pop(self.order.pop(0), None)
            return stream

    def reset(self, review_id: str) -> EventStream:
        stream = self.stream_for(review_id)
        stream.restart()
        return stream
