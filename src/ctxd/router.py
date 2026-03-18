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
