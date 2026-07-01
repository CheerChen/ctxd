"""URL routing for ctxd."""

from __future__ import annotations

import re
from enum import Enum


class Source(Enum):
    GITHUB_PR = "github_pr"
    SLACK_THREAD = "slack_thread"
    CONFLUENCE = "confluence"
    JIRA = "jira"


ROUTES: list[tuple[re.Pattern[str], Source]] = [
    (re.compile(r"https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)"), Source.GITHUB_PR),
    (re.compile(r"https?://[^/]*slack\.com/.*(archives|client)/"), Source.SLACK_THREAD),
    (re.compile(r"https?://[^/]*atlassian\.net/wiki/"), Source.CONFLUENCE),
    (re.compile(r"https?://[^/]*atlassian\.net/browse/"), Source.JIRA),
]


_GITHUB_PR_RE = re.compile(r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)")
_SLACK_ARCHIVES_RE = re.compile(r"/archives/(?P<channel>[A-Z0-9]+)/p(?P<ts>\d{16,})")
_SLACK_CLIENT_RE = re.compile(
    r"/client/[^/]+/(?P<channel>[A-Z0-9]+)/thread/[^/-]+-(?P<ts>\d+\.\d+)"
)


def detect(url: str) -> Source:
    for pattern, source in ROUTES:
        if pattern.search(url):
            return source
    raise ValueError(f"Unsupported URL: {url}")


def parse_github_pr_url(url: str) -> tuple[str, str, str]:
    match = _GITHUB_PR_RE.search(url)
    if not match:
        raise ValueError(f"Invalid GitHub PR URL: {url}")
    return match.group("owner"), match.group("repo"), match.group("number")


def parse_slack_thread_url(url: str) -> tuple[str, str]:
    client_match = _SLACK_CLIENT_RE.search(url)
    if client_match:
        return client_match.group("channel"), client_match.group("ts")

    archives_match = _SLACK_ARCHIVES_RE.search(url)
    if not archives_match:
        raise ValueError(f"Unsupported Slack thread URL: {url}")

    channel = archives_match.group("channel")
    raw_ts = archives_match.group("ts")

    query_match = re.search(r"[?&]thread_ts=(\d+\.\d+)", url)
    if query_match:
        return channel, query_match.group(1)

    return channel, f"{raw_ts[:10]}.{raw_ts[10:16]}"


def parse_slack_focused_ts(url: str) -> str | None:
    """Extract the focused message ts from a Slack archives URL.

    Slack archives URLs embed the focused message in the path (``/p<ts>``)
    and the thread root in the ``thread_ts`` query param. When they differ,
    the user copied a link to a specific reply — we return that reply's ts
    so the dumper can highlight it. When they're the same (or the URL is a
    client-format thread URL), the user pointed at the thread root, so we
    return None (no special highlight needed).
    """
    archives_match = _SLACK_ARCHIVES_RE.search(url)
    if not archives_match:
        return None  # client URL — ts is already the thread root

    raw_ts = archives_match.group("ts")
    path_ts = f"{raw_ts[:10]}.{raw_ts[10:16]}"

    query_match = re.search(r"[?&]thread_ts=(\d+\.\d+)", url)
    if not query_match:
        return None  # no thread_ts → /p<ts> IS the thread root

    thread_ts = query_match.group(1)
    if path_ts == thread_ts:
        return None  # focused message is the thread root

    return path_ts
