import pytest
import requests

from conftest import FakeGitHubClient
from ctxd.dumpers.github_pr import GitHubPRDumper
from ctxd.github.api_client import GitHubAPIError


def test_clean_pr_body_extracts_file_walkthrough() -> None:
    body = """
<details>
<summary>File Walkthrough</summary>
<strong>foo.py</strong><code>refactor parser</code>
<a href=\"x\"> +10/-2 </a>
</details>
"""
    cleaned = GitHubPRDumper.clean_pr_body(body)
    assert "[File Changes]" in cleaned
    assert "foo.py: refactor parser (+10/-2)" in cleaned


def test_clean_pr_body_strips_html() -> None:
    body = "Hello <a href=\"x\">world</a> &amp; all&nbsp;"
    cleaned = GitHubPRDumper.clean_pr_body(body)
    assert "<a" not in cleaned
    assert "Hello world & all" in cleaned


# ---------------------------------------------------------------------------
# Never silent: API and diff failures warn under --quiet and count as failed
# ---------------------------------------------------------------------------


def _quiet_dumper(fail: Exception) -> GitHubPRDumper:
    d = GitHubPRDumper(url="https://github.com/o/r/pull/1", output=None, fmt="md", quiet=True)
    d.owner, d.repo, d.pr_number = "o", "r", "1"
    d.client = FakeGitHubClient(fail=fail)
    return d


@pytest.mark.parametrize("fail, message", [
    (GitHubAPIError("GitHub API 403: rate limited"), "rate limited"),
    (requests.ConnectionError("connection reset"), "connection reset"),
    (ValueError("Expecting value: line 1 column 1"), "Expecting value"),
])
def test_failed_api_call_returns_nothing_warns_and_counts(capsys, fail, message) -> None:
    d = _quiet_dumper(fail)

    assert d._paginate("/repos/o/r/issues/1/comments") == []

    err = capsys.readouterr().err
    assert "GitHub API call failed" in err and message in err
    assert d.summary.failed == 1
    assert any(message in note for note in d.summary.notes)


def test_failed_diff_fetch_warns_and_counts(capsys) -> None:
    d = _quiet_dumper(requests.ConnectionError("network error"))

    assert d._fetch_unified_diff() == ""

    err = capsys.readouterr().err
    assert "PR diff fetch failed" in err and "network error" in err
    assert d.summary.failed == 1


# ---------------------------------------------------------------------------
# Fetch: comments and reviews, and --no-bots
# ---------------------------------------------------------------------------

def _user(login: str, bot: bool = False) -> dict:
    return {"login": login, "type": "Bot" if bot else "User"}


_PAGES = {
    "/repos/o/r/issues/1/comments": [
        {"body": "human note", "user": _user("alice"), "created_at": "2026-04-20T01:00:00Z"},
        {"body": "bot note", "user": _user("ci-bot", bot=True), "created_at": "2026-04-20T02:00:00Z"},
        {"body": "   ", "user": _user("alice")},
    ],
    "/repos/o/r/pulls/1/comments": [
        {"body": "inline human", "user": _user("alice"), "path": "a.py", "line": 3},
        {"body": "inline bot", "user": _user("lint-bot", bot=True), "path": "a.py", "line": 4},
    ],
    "/repos/o/r/pulls/1/reviews": [
        {"state": "APPROVED", "body": "lgtm", "user": _user("bob")},
        {"state": "COMMENTED", "body": "bot review", "user": _user("review-bot", bot=True)},
        {"state": "PENDING", "body": "my draft", "user": _user("bob")},
    ],
}


@pytest.mark.parametrize("no_bots", [False, True])
def test_comments_and_reviews_are_exported_and_no_bots_drops_bots(monkeypatch, no_bots: bool) -> None:
    from conftest import install_fake_github

    install_fake_github(monkeypatch, pull={"title": "T", "body": "B"}, pages=_PAGES)
    out = GitHubPRDumper(url="https://github.com/o/r/pull/1", output=None, fmt="md",
                         quiet=True, no_bots=no_bots).render()

    for human in ("human note", "inline human", "lgtm"):
        assert human in out
    assert "my draft" not in out  # PENDING reviews are the author's own drafts
    for bot in ("bot note", "inline bot", "bot review"):
        assert (bot in out) is not no_bots
