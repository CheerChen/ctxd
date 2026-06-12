"""Lightweight profiler for ctxd.

Enabled via --profile flag. Records:
- HTTP request counts and network time per source (Slack/Confluence/Jira/attachments)
- subprocess call counts and wall time (gh)
- Coarse pipeline stages (fetch / transform / attachments / comments)

Output is a stderr table printed after the dumper finishes.
"""

from __future__ import annotations

import sys
import threading
import time
from contextlib import contextmanager
from typing import Iterator


class Profiler:
    def __init__(self) -> None:
        self.enabled = False
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}
        self._totals: dict[str, float] = {}
        self._start = 0.0

    def enable(self) -> None:
        self.enabled = True
        self._start = time.perf_counter()

    def record(self, label: str, seconds: float = 0.0, count: int = 1) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._counts[label] = self._counts.get(label, 0) + count
            self._totals[label] = self._totals.get(label, 0.0) + seconds

    @contextmanager
    def timed(self, label: str) -> Iterator[None]:
        if not self.enabled:
            yield
            return
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.record(label, time.perf_counter() - t0)

    def instrument_session(self, session, label: str) -> None:
        if not self.enabled:
            return
        bucket = f"http.{label}"

        def hook(resp, *args, **kwargs):
            elapsed = resp.elapsed.total_seconds() if resp.elapsed else 0.0
            self.record(bucket, elapsed)

            status_class = resp.status_code // 100
            if status_class != 2:
                self.record(f"{bucket}.{status_class}xx", elapsed)

            # urllib3 records retry attempts on resp.raw.retries.history when
            # an HTTPAdapter with a Retry policy is mounted. Surface them so
            # transient failures don't get buried in the total time.
            try:
                retries = getattr(resp.raw, "retries", None)
                history = getattr(retries, "history", None) if retries else None
                if history:
                    self.record(f"{bucket}.retry", 0.0, count=len(history))
            except Exception:
                pass

        session.hooks.setdefault("response", []).append(hook)

    def report(self) -> str:
        if not self.enabled:
            return ""
        wall = time.perf_counter() - self._start
        keys = sorted(
            set(self._counts) | set(self._totals),
            key=lambda k: (-self._totals.get(k, 0.0), k),
        )
        label_w = max((len(k) for k in keys), default=5)
        label_w = max(label_w, len("label"))
        sep = "─" * (label_w + 22)
        lines = [
            "",
            sep,
            f"ctxd profile  (wall {wall:.2f}s)",
            sep,
            f"{'label':<{label_w}}  {'count':>6}  {'time(s)':>9}",
        ]
        for key in keys:
            cnt = self._counts.get(key, 0)
            t = self._totals.get(key, 0.0)
            lines.append(f"{key:<{label_w}}  {cnt:>6}  {t:>9.3f}")
        lines.append(sep)
        return "\n".join(lines)


PROFILER = Profiler()


def enable_profiling() -> None:
    PROFILER.enable()


def is_enabled() -> bool:
    return PROFILER.enabled


def timed(label: str):
    return PROFILER.timed(label)


def record(label: str, seconds: float = 0.0, count: int = 1) -> None:
    PROFILER.record(label, seconds, count)


def instrument_session(session, label: str) -> None:
    PROFILER.instrument_session(session, label)


def emit_report() -> None:
    if not PROFILER.enabled:
        return
    sys.stderr.write(PROFILER.report() + "\n")
    sys.stderr.flush()
