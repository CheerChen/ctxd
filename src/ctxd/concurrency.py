"""Concurrency helpers for ctxd.

Provides a single tunable cap (set from --max-concurrency) and a
`parallel_map` helper that preserves input order and degrades gracefully
to a serial map when the cap is 1.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, TypeVar

_DEFAULT_MAX = 5
_configured_max = _DEFAULT_MAX

T = TypeVar("T")
R = TypeVar("R")


def configure(max_concurrency: int) -> None:
    global _configured_max
    _configured_max = max(1, int(max_concurrency))


def get_max() -> int:
    return _configured_max


def parallel_map(
    fn: Callable[[T], R],
    items: Iterable[T],
    max_workers: int | None = None,
) -> list[R]:
    """Map fn over items concurrently while preserving input order.

    max_workers defaults to the global cap (see configure). Passing <=1
    runs serially. Exceptions propagate to the caller — first one wins.
    """
    materialized = list(items)
    if not materialized:
        return []

    cap = max_workers if max_workers is not None else _configured_max
    workers = min(len(materialized), max(1, cap))
    if workers == 1:
        return [fn(item) for item in materialized]

    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(fn, materialized))
