"""Shared retry policy for ctxd HTTP sessions.

Honors `Retry-After` headers from Atlassian / Slack so we back off correctly
on 429. Only retries idempotent methods.
"""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def mount_retry(
    session: requests.Session,
    total: int = 3,
    backoff: float = 1.0,
    methods: frozenset[str] = frozenset(["GET", "HEAD"]),
) -> None:
    """Attach a Retry policy that handles 429 / 5xx with Retry-After.

    Slack's Web API uses POST for idempotent reads, so callers pass an
    extended method set when appropriate.
    """
    retry = Retry(
        total=total,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=methods,
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
