from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from trader.storage.store import Store


class SourceTracker(Protocol):
    def start_fetch(self, source: str) -> None: ...

    def record_fetch(self, source: str, *, item_count: int, error: str | None = None) -> None: ...

    def record_persisted_counts(self, counts: dict[str, int]) -> None: ...


@dataclass
class _FetchRecord:
    fetch_id: str
    started_perf: float
    status: str = "running"
    item_count: int = 0
    persisted_count: int = 0
    latency_ms: int = 0
    error: str = ""


class StoreSourceHealthTracker:
    def __init__(self, store: Store, *, lookback_days: int | None = None, clock=time.perf_counter) -> None:
        self.store = store
        self.lookback_days = lookback_days
        self._clock = clock
        self._records: dict[str, _FetchRecord] = {}

    def start_fetch(self, source: str) -> None:
        self._records[source] = _FetchRecord(
            fetch_id=self.store.start_source_fetch(source, lookback_days=self.lookback_days),
            started_perf=self._clock(),
        )

    def record_fetch(self, source: str, *, item_count: int, error: str | None = None) -> None:
        record = self._records.get(source)
        if record is None:
            self.start_fetch(source)
            record = self._records[source]

        status = "error" if error else ("ok" if item_count > 0 else "empty")
        latency_ms = max(0, round((self._clock() - record.started_perf) * 1000))
        record.status = status
        record.item_count = int(item_count)
        record.latency_ms = latency_ms
        record.error = error or ""
        self.store.finish_source_fetch(
            record.fetch_id,
            status=status,
            item_count=record.item_count,
            persisted_count=record.persisted_count,
            latency_ms=latency_ms,
            error=record.error,
        )

    def record_persisted_counts(self, counts: dict[str, int]) -> None:
        for source, persisted_count in counts.items():
            record = self._records.get(source)
            if record is None:
                continue
            record.persisted_count = int(persisted_count)
            if record.status == "running":
                continue
            self.store.finish_source_fetch(
                record.fetch_id,
                status=record.status,
                item_count=record.item_count,
                persisted_count=record.persisted_count,
                latency_ms=record.latency_ms,
                error=record.error,
            )


class CompositeSourceTracker:
    def __init__(self, *trackers: object) -> None:
        self.trackers = trackers

    def start_fetch(self, source: str) -> None:
        for tracker in self.trackers:
            start = getattr(tracker, "start_fetch", None)
            if start is not None:
                start(source)

    def record_fetch(self, source: str, *, item_count: int, error: str | None = None) -> None:
        for tracker in self.trackers:
            record = getattr(tracker, "record_fetch", None)
            if record is not None:
                record(source, item_count=item_count, error=error)

    def record_persisted_counts(self, counts: dict[str, int]) -> None:
        for tracker in self.trackers:
            record = getattr(tracker, "record_persisted_counts", None)
            if record is not None:
                record(counts)
