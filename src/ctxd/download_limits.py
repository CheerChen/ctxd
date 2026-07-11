"""Size limits for attachment downloads.

Enforces per-file and per-run caps to prevent runaway downloads from
filling the disk.  Defaults are conservative:
- per-file: 50 MiB
- per-run:  500 MiB

Both can be overridden via environment variables:
- CTXD_MAX_FILE_BYTES
- CTXD_MAX_RUN_BYTES
"""

from __future__ import annotations

import os
import threading

_MIB = 1024 * 1024

DEFAULT_MAX_FILE_BYTES = int(os.environ.get("CTXD_MAX_FILE_BYTES", str(50 * _MIB)))
DEFAULT_MAX_RUN_BYTES = int(os.environ.get("CTXD_MAX_RUN_BYTES", str(500 * _MIB)))


class DownloadLimitExceeded(Exception):
    """Raised when a download exceeds the per-file or per-run cap."""


class RunBudget:
    """Tracks total bytes downloaded in a single ctxd run.

    Thread-safe — safe to call ``check_and_reserve`` from parallel workers.
    A *max_run_bytes* of -1 (or any negative value) means unlimited.
    """

    def __init__(self, max_run_bytes: int = DEFAULT_MAX_RUN_BYTES) -> None:
        self._max = max_run_bytes
        self._used = 0
        self._lock = threading.Lock()

    def check_and_reserve(self, file_bytes: int) -> None:
        """Raise DownloadLimitExceeded if *file_bytes* would push the
        run total past the cap.  Otherwise add *file_bytes* to the used total.

        If the budget is negative (unlimited), always succeeds.
        """
        if self._max < 0:
            return  # Unlimited
        with self._lock:
            if self._used + file_bytes > self._max:
                raise DownloadLimitExceeded(
                    f"run budget exceeded: {self._used + file_bytes} > {self._max} bytes"
                )
            self._used += file_bytes

    @property
    def used(self) -> int:
        return self._used

    @property
    def max(self) -> int:
        return self._max
