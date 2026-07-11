"""Tests for the never-silent rule: warnings survive ``--quiet``.

``log()`` is progress (suppressed by quiet); ``warn()`` is diagnostic
(always visible).  Data-loss paths must use ``warn()``.
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest

from ctxd.dumpers.base import BaseDumper
from ctxd.dumpers.github_pr import GitHubPRDumper
from ctxd.dumpers.slack import SlackDumper


# ---------------------------------------------------------------------------
# BaseDumper.log vs BaseDumper.warn
# ---------------------------------------------------------------------------

class _ConcreteDumper(BaseDumper):
    """Minimal concrete dumper for testing log/warn."""

    def validate_auth(self) -> None: ...
    def fetch(self) -> dict: return {}
    def transform(self, raw: dict) -> str: return ""
    def default_filename(self) -> str: return "test.txt"


class TestLogWarnSeparation:
    def test_log_suppressed_by_quiet(self, capsys: pytest.CaptureFixture) -> None:
        d = _ConcreteDumper(url="x", output=None, fmt="md", quiet=True)
        d.log("progress message")
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_log_visible_without_quiet(self, capsys: pytest.CaptureFixture) -> None:
        d = _ConcreteDumper(url="x", output=None, fmt="md", quiet=False)
        d.log("progress message")
        captured = capsys.readouterr()
        assert "progress message" in captured.err

    def test_warn_visible_even_with_quiet(self, capsys: pytest.CaptureFixture) -> None:
        d = _ConcreteDumper(url="x", output=None, fmt="md", quiet=True)
        d.warn("data loss warning")
        captured = capsys.readouterr()
        assert "data loss warning" in captured.err

    def test_warn_visible_without_quiet(self, capsys: pytest.CaptureFixture) -> None:
        d = _ConcreteDumper(url="x", output=None, fmt="md", quiet=False)
        d.warn("data loss warning")
        captured = capsys.readouterr()
        assert "data loss warning" in captured.err


# ---------------------------------------------------------------------------
# GitHub PR: _gh_api_paginate warns on failure
# ---------------------------------------------------------------------------

class TestGitHubPRNeverSilent:
    def _make_dumper(self, quiet: bool = True) -> GitHubPRDumper:
        d = GitHubPRDumper(
            url="https://github.com/o/r/pull/1",
            output=None, fmt="md", quiet=quiet,
        )
        d.owner = "o"
        d.repo = "r"
        d.pr_number = "1"
        return d

    def test_api_paginate_warns_on_nonzero_exit(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        d = self._make_dumper(quiet=True)
        proc = MagicMock(returncode=1, stderr="rate limited", stdout="")
        with patch("ctxd.dumpers.github_pr.subprocess.run", return_value=proc):
            result = d._gh_api_paginate("/repos/o/r/issues/1/comments")
        assert result == []
        captured = capsys.readouterr()
        assert "GitHub API call failed" in captured.err
        assert "rate limited" in captured.err

    def test_api_paginate_warns_on_json_error(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        d = self._make_dumper(quiet=True)
        proc = MagicMock(returncode=0, stderr="", stdout="not json")
        with patch("ctxd.dumpers.github_pr.subprocess.run", return_value=proc):
            result = d._gh_api_paginate("/repos/o/r/issues/1/comments")
        assert result == []
        captured = capsys.readouterr()
        assert "not valid JSON" in captured.err

    def test_diff_fetch_warns_on_failure(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        d = self._make_dumper(quiet=True)
        proc = MagicMock(returncode=1, stderr="network error", stdout="")
        with patch("ctxd.dumpers.github_pr.subprocess.run", return_value=proc):
            result = d._fetch_unified_diff()
        assert result == ""
        captured = capsys.readouterr()
        assert "PR diff fetch failed" in captured.err
        assert "network error" in captured.err


# ---------------------------------------------------------------------------
# Slack: _get_user and _get_channel_name warn on failure
# ---------------------------------------------------------------------------

class TestSlackNeverSilent:
    def _make_dumper(self, quiet: bool = True) -> SlackDumper:
        return SlackDumper(
            url="https://app.slack.com/client/T123/C123/thread/C123-1234567890.123456",
            output=None, fmt="md", quiet=quiet,
        )

    def test_get_user_warns_on_failure(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        d = self._make_dumper(quiet=True)
        d.token = "xoxp-fake"
        # Force _api_call to raise
        with patch.object(d, "_api_call", side_effect=RuntimeError("boom")):
            result = d._get_user("U123")
        assert result["id"] == "U123"
        assert result["name"] == "U123"
        captured = capsys.readouterr()
        assert "failed to resolve user U123" in captured.err
        assert "boom" in captured.err

    def test_get_channel_name_warns_on_failure(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        d = self._make_dumper(quiet=True)
        d.token = "xoxp-fake"
        with patch.object(d, "_api_call", side_effect=RuntimeError("boom")):
            result = d._get_channel_name("C123")
        assert result == "C123"
        captured = capsys.readouterr()
        assert "failed to resolve channel C123" in captured.err
        assert "boom" in captured.err

    def test_download_failure_warns_even_when_quiet(
        self, capsys: pytest.CaptureFixture, tmp_path: pytest.PathCaptureFixture
    ) -> None:
        d = self._make_dumper(quiet=True)
        d.token = "xoxp-fake"
        files = [{"url_private_download": "https://files.slack.com/x", "name": "test.png", "id": "F1"}]
        with patch.object(d.session, "get", side_effect=RuntimeError("network error")):
            d._download_files(files, tmp_path)
        captured = capsys.readouterr()
        assert "Failed to download test.png" in captured.err
        assert "network error" in captured.err

    def test_html_response_warning_survives_quiet(
        self, capsys: pytest.CaptureFixture, tmp_path: pytest.PathCaptureFixture
    ) -> None:
        d = self._make_dumper(quiet=True)
        d.token = "xoxp-fake"
        files = [{"url_private_download": "https://files.slack.com/x", "name": "test.png", "id": "F1"}]
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.headers = {"content-type": "text/html; charset=utf-8"}
        with patch.object(d.session, "get", return_value=resp):
            d._download_files(files, tmp_path)
        captured = capsys.readouterr()
        assert "got HTML instead of binary" in captured.err
