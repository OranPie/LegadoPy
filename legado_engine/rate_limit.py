from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConcurrentRateRecord:
    is_concurrent: bool
    time_ms: int
    frequency: int
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class ConcurrentRateLease:
    def __init__(self, record: ConcurrentRateRecord | None) -> None:
        self._record = record

    def release(self) -> None:
        if self._record is None or self._record.is_concurrent:
            return
        with self._record.lock:
            self._record.frequency -= 1

    def __enter__(self) -> "ConcurrentRateLease":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


def acquire_rate_limit(
    source: Any,
    rate_limit_records: dict[str, ConcurrentRateRecord],
    rate_limit_lock: threading.Lock,
) -> ConcurrentRateLease:
    """Acquire a rate-limit lease for the given source, blocking if needed."""
    source_key = ""
    if source is not None:
        source_key = (
            getattr(source, "get_key", lambda: "")()
            or getattr(source, "getKey", lambda: "")()
            or getattr(source, "bookSourceUrl", "")
            or getattr(source, "sourceUrl", "")
        )
    concurrent_rate = (getattr(source, "concurrentRate", None) or "").strip()
    if not source_key or not concurrent_rate or concurrent_rate == "0":
        return ConcurrentRateLease(None)

    rate_index = concurrent_rate.find("/")
    while True:
        now_ms = int(time.time() * 1000)
        with rate_limit_lock:
            record = rate_limit_records.get(source_key)
            if record is None:
                record = ConcurrentRateRecord(
                    is_concurrent=rate_index > 0,
                    time_ms=now_ms,
                    frequency=1,
                )
                rate_limit_records[source_key] = record
                return ConcurrentRateLease(record)

        wait_ms = 0
        with record.lock:
            try:
                if not record.is_concurrent:
                    limit_ms = int(concurrent_rate)
                    if record.frequency > 0:
                        wait_ms = limit_ms
                    else:
                        next_time = record.time_ms + limit_ms
                        if now_ms >= next_time:
                            record.time_ms = now_ms
                            record.frequency = 1
                            return ConcurrentRateLease(record)
                        wait_ms = next_time - now_ms
                else:
                    max_count = int(concurrent_rate[:rate_index])
                    window_ms = int(concurrent_rate[rate_index + 1:])
                    next_time = record.time_ms + window_ms
                    if now_ms >= next_time:
                        record.time_ms = now_ms
                        record.frequency = 1
                        return ConcurrentRateLease(record)
                    if record.frequency > max_count:
                        wait_ms = next_time - now_ms
                    else:
                        record.frequency += 1
                        return ConcurrentRateLease(record)
            except Exception:
                return ConcurrentRateLease(None)

        if wait_ms > 0:
            time.sleep(wait_ms / 1000.0)
