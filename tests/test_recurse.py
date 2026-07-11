"""Tests for cross-source recursive expansion."""

from __future__ import annotations

from ctxd.auth import AuthError
from ctxd.recurse import MAX_CHILDREN_PER_LEVEL, extract_supported_urls, render_with_recurse
from ctxd.summary import Summary

import pytest


# ---------------------------------------------------------------------------
# extract_supported_urls
# ---------------------------------------------------------------------------

def test_extract_finds_all_four_source_types() -> None:
    text = (
        "See https://app.slack.com/client/T/C123/thread/C123-1234567890.123456 "
        "and https://github.com/owner/repo/pull/42 "
        "and https://site.atlassian.net/wiki/spaces/ABC/pages/123/title "
        "and https://site.atlassian.net/browse/PROJ-1"
    )
    urls = extract_supported_urls(text)
    assert len(urls) == 4
    assert "https://app.slack.com/client/T/C123/thread/C123-1234567890.123456" in urls
    assert "https://github.com/owner/repo/pull/42" in urls
    assert "https://site.atlassian.net/wiki/spaces/ABC/pages/123/title" in urls
    assert "https://site.atlassian.net/browse/PROJ-1" in urls


def test_extract_ignores_non_supported_urls() -> None:
    text = "Check https://example.com and https://github.com/owner/repo/issues/5"
    urls = extract_supported_urls(text)
    assert urls == []


def test_extract_deduplicates() -> None:
    url = "https://github.com/owner/repo/pull/42"
    text = f"See {url} and again {url}"
    urls = extract_supported_urls(text)
    assert urls == [url]


def test_extract_excludes_self() -> None:
    url = "https://github.com/owner/repo/pull/42"
    text = f"See {url}"
    urls = extract_supported_urls(text, exclude={url})
    assert urls == []


def test_extract_preserves_order() -> None:
    text = (
        "First https://site.atlassian.net/browse/PROJ-1 "
        "then https://github.com/owner/repo/pull/42"
    )
    urls = extract_supported_urls(text)
    assert urls[0] == "https://site.atlassian.net/browse/PROJ-1"
    assert urls[1] == "https://github.com/owner/repo/pull/42"


def test_extract_strips_trailing_punctuation() -> None:
    text = "See https://github.com/owner/repo/pull/42, and https://site.atlassian.net/browse/PROJ-1."
    urls = extract_supported_urls(text)
    assert "https://github.com/owner/repo/pull/42" in urls
    assert "https://site.atlassian.net/browse/PROJ-1" in urls


def test_extract_ignores_slack_channel_urls() -> None:
    """Channel URLs (/archives/C123 without /p<ts>) match detect() but aren't
    valid thread targets — they should be filtered out."""
    text = "Channel: https://example.slack.com/archives/C12345678 Thread: https://example.slack.com/archives/C12345678/p1782879875064939"
    urls = extract_supported_urls(text)
    assert len(urls) == 1
    assert "p1782879875064939" in urls[0]


# ---------------------------------------------------------------------------
# render_with_recurse — fake dumper helpers
# ---------------------------------------------------------------------------

class _FakeDumper:
    """Minimal dumper stub for recursion tests."""

    def __init__(self, url: str, content: str = "content\n", fail: Exception | None = None):
        self.url = url
        self.output = None
        self.fmt = "md"
        self.quiet = True
        self.verbose = False
        self.summary = Summary()
        self._content = content
        self._fail = fail

    def render(self) -> str:
        if self._fail:
            raise self._fail
        return self._content

    def log(self, message: str) -> None:
        pass


def _make_factory(contents: dict[str, str] | None = None, fails: dict[str, Exception] | None = None):
    """Return a function that builds a _FakeDumper for a given URL."""
    contents = contents or {}
    fails = fails or {}

    def factory(url: str, opts) -> _FakeDumper:
        return _FakeDumper(
            url=url,
            content=contents.get(url, f"content for {url}\n"),
            fail=fails.get(url),
        )

    return factory


# ---------------------------------------------------------------------------
# render_with_recurse
# ---------------------------------------------------------------------------

def test_depth_zero_no_recurse(monkeypatch) -> None:
    dumper = _FakeDumper(
        url="https://app.slack.com/client/T/C/thread/C-123.456",
        content="just the thread\n",
    )
    result = render_with_recurse(dumper, depth=0)
    assert result == "just the thread\n"


def test_depth_one_recurse_one_child(monkeypatch) -> None:
    parent_url = "https://app.slack.com/client/T/C/thread/C-123.456"
    child_url = "https://site.atlassian.net/browse/PROJ-1"
    parent_content = f"See {child_url} for details.\n"
    child_content = "# [PROJ-1] Issue\n\nbody\n"

    dumper = _FakeDumper(url=parent_url, content=parent_content)
    factory = _make_factory({child_url: child_content})
    monkeypatch.setattr("ctxd.recurse._build_dumper", factory)

    result = render_with_recurse(dumper, depth=1)

    assert "just the thread" in result[:50] or parent_content in result[:100]
    assert "---" in result
    assert f"recursed from {child_url}" in result
    assert child_content in result


@pytest.mark.parametrize("exc,expected_msg", [
    (AuthError("missing Slack token"), "missing Slack token"),
    (RuntimeError("network error"), "network error"),
])
def test_child_error_skipped_not_raised(monkeypatch, exc, expected_msg) -> None:
    parent_url = "https://app.slack.com/client/T/C/thread/C-123.456"
    child_url = "https://site.atlassian.net/browse/PROJ-1"
    parent_content = f"See {child_url}\n"

    dumper = _FakeDumper(url=parent_url, content=parent_content)
    factory = _make_factory(fails={child_url: exc})
    monkeypatch.setattr("ctxd.recurse._build_dumper", factory)

    result = render_with_recurse(dumper, depth=1)

    assert f"recursed from {child_url}" in result
    assert "skipped" in result
    assert expected_msg in result


def test_seen_dedup_across_levels(monkeypatch) -> None:
    parent_url = "https://app.slack.com/client/T/C/thread/C-123.456"
    child_url = "https://site.atlassian.net/browse/PROJ-1"
    # Both parent and child mention the same child_url
    parent_content = f"See {child_url}\n"
    child_content = f"Also see {child_url} again\n"

    dumper = _FakeDumper(url=parent_url, content=parent_content)
    factory = _make_factory({child_url: child_content})
    monkeypatch.setattr("ctxd.recurse._build_dumper", factory)

    result = render_with_recurse(dumper, depth=2)

    # child_url should appear exactly once in the appendix
    recurse_markers = [line for line in result.splitlines() if "recursed from" in line]
    assert len(recurse_markers) == 1


def test_child_cap_truncation(monkeypatch) -> None:
    parent_url = "https://app.slack.com/client/T/C/thread/C-123.456"
    # Generate more URLs than the cap
    child_urls = [
        f"https://site.atlassian.net/browse/PROJ-{i}" for i in range(MAX_CHILDREN_PER_LEVEL + 3)
    ]
    parent_content = "See " + " ".join(child_urls) + "\n"

    dumper = _FakeDumper(url=parent_url, content=parent_content)
    factory = _make_factory({u: f"content {u}\n" for u in child_urls})
    monkeypatch.setattr("ctxd.recurse._build_dumper", factory)

    result = render_with_recurse(dumper, depth=1)

    recurse_markers = [line for line in result.splitlines() if "recursed from" in line]
    truncation_markers = [line for line in result.splitlines() if "truncated" in line]
    # Exactly MAX_CHILDREN_PER_LEVEL rendered + 1 truncation notice
    assert len(recurse_markers) == MAX_CHILDREN_PER_LEVEL
    assert len(truncation_markers) == 1


def test_no_supported_urls_returns_unchanged(monkeypatch) -> None:
    dumper = _FakeDumper(
        url="https://app.slack.com/client/T/C/thread/C-123.456",
        content="just a plain message with no links\n",
    )
    result = render_with_recurse(dumper, depth=1)
    assert result == "just a plain message with no links\n"


def test_depth_two_nested_recursion(monkeypatch) -> None:
    parent_url = "https://app.slack.com/client/T/C/thread/C-123.456"
    child_url = "https://site.atlassian.net/browse/PROJ-1"
    grandchild_url = "https://github.com/owner/repo/pull/42"

    parent_content = f"See {child_url}\n"
    child_content = f"Issue references {grandchild_url}\n"
    grandchild_content = "# PR #42\n\nbody\n"

    dumper = _FakeDumper(url=parent_url, content=parent_content)
    factory = _make_factory({
        child_url: child_content,
        grandchild_url: grandchild_content,
    })
    monkeypatch.setattr("ctxd.recurse._build_dumper", factory)

    result = render_with_recurse(dumper, depth=2)

    assert f"recursed from {child_url}" in result
    assert f"recursed from {grandchild_url}" in result
    # Grandchild should have nested numbering [1.1]
    assert "[1.1]" in result
