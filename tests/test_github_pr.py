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
