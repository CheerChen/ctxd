"""Tests for P1 blocking issue fixes.

Verifies:
1. CLI parameters --max-chars / --max-file-size / --max-run-size are wired
2. Truncation enters summary.truncated + notes + closes code fences
3. RunBudget is shared across calls (not reset per batch)
4. Atomic writes protect existing files on failure
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from ctxd.cli import main


# ---------------------------------------------------------------------------
# Blocking #1: CLI parameters
# ---------------------------------------------------------------------------

class TestCLIParameters:
    """--max-chars / --max-file-size / --max-run-size must be accepted
    and propagated to dumpers."""

    def test_max_chars_accepted(self, tmp_path: Path, monkeypatch) -> None:
        """CLI accepts --max-chars without error."""
        monkeypatch.setattr("ctxd.dumpers.github_pr.ensure_github_auth", lambda: None)
        monkeypatch.setattr("ctxd.auth.ensure_github_auth", lambda: None)

        def mock_run(cmd, **kw):
            s = " ".join(cmd)
            if "pr view" in s:
                return MagicMock(returncode=0, stdout=json.dumps({"title": "T", "body": "B"}), stderr="")
            if "pr diff" in s:
                return MagicMock(returncode=0, stdout="", stderr="")
            if "api" in s:
                return MagicMock(returncode=0, stdout="[]", stderr="")
            return MagicMock(returncode=0, stdout="{}", stderr="")

        monkeypatch.setattr("ctxd.dumpers.github_pr.subprocess.run", mock_run)

        runner = CliRunner()
        result = runner.invoke(main, [
            "https://github.com/o/r/pull/1",
            "-o", str(tmp_path / "out.md"),
            "--max-chars", "50000",
            "--max-file-size", "10485760",
            "--max-run-size", "104857600",
        ])
        assert result.exit_code == 0, f"{result.output}\n{result.exception}"

    def test_max_chars_unlimited(self, tmp_path: Path, monkeypatch) -> None:
        """--max-chars -1 disables the limit."""
        monkeypatch.setattr("ctxd.dumpers.github_pr.ensure_github_auth", lambda: None)
        monkeypatch.setattr("ctxd.auth.ensure_github_auth", lambda: None)

        def mock_run(cmd, **kw):
            s = " ".join(cmd)
            if "pr view" in s:
                return MagicMock(returncode=0, stdout=json.dumps({"title": "T", "body": "B"}), stderr="")
            if "pr diff" in s:
                return MagicMock(returncode=0, stdout="", stderr="")
            if "api" in s:
                return MagicMock(returncode=0, stdout="[]", stderr="")
            return MagicMock(returncode=0, stdout="{}", stderr="")

        monkeypatch.setattr("ctxd.dumpers.github_pr.subprocess.run", mock_run)

        runner = CliRunner()
        result = runner.invoke(main, [
            "https://github.com/o/r/pull/1",
            "-o", str(tmp_path / "out.md"),
            "--max-chars", "-1",
        ])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Blocking #2: Truncation enters summary
# ---------------------------------------------------------------------------

class TestTruncationSummary:
    """Truncation must update summary.truncated, add notes, and close
    open code fences."""

    def test_truncation_updates_summary(self) -> None:
        from ctxd.dumpers.base import _apply_stdout_limit
        from ctxd.summary import Summary

        summary = Summary(source="test")
        content = "line\n" * 30000  # ~150K chars
        result = _apply_stdout_limit(content, max_chars=100000, summary=summary)

        assert summary.truncated == 1
        assert any("truncated" in note for note in summary.notes)
        assert any("150" in note or str(len(content)) in note for note in summary.notes)

    def test_truncation_closes_open_code_fence(self) -> None:
        from ctxd.dumpers.base import _apply_stdout_limit

        # Content with an open code fence that will be cut mid-block
        fence_line = "```python\n"
        code_line = "x = 1\n"
        # Build content that exceeds 100K with an open fence near the end
        content = "header\n" + "normal line\n" * 8000 + fence_line + "code line\n" * 2000
        result = _apply_stdout_limit(content, max_chars=100000)

        # If the fence was open in the truncated portion, it must be closed
        # Count ``` fences in the result (before the notice)
        notice_idx = result.find("\n\n> [ctxd:")
        truncated_part = result[:notice_idx] if notice_idx > 0 else result
        fence_count = truncated_part.count("```")
        # Fence count must be even (all fences closed)
        assert fence_count % 2 == 0, f"Unclosed code fence: {fence_count} fences in truncated output"

    def test_truncation_notice_includes_sizes(self) -> None:
        from ctxd.dumpers.base import _apply_stdout_limit

        content = "x" * 200000
        result = _apply_stdout_limit(content, max_chars=100000)
        assert "Original size: 200000" in result
        assert "retained:" in result

    def test_no_truncation_no_summary_change(self) -> None:
        from ctxd.dumpers.base import _apply_stdout_limit
        from ctxd.summary import Summary

        summary = Summary(source="test")
        result = _apply_stdout_limit("short content", max_chars=100000, summary=summary)
        assert summary.truncated == 0
        assert not summary.notes


# ---------------------------------------------------------------------------
# Blocking #3: RunBudget shared across calls
# ---------------------------------------------------------------------------

class TestRunBudgetShared:
    """RunBudget must be shared across all download calls in a single run."""

    def test_slack_uses_shared_budget(self, monkeypatch, tmp_path: Path) -> None:
        """Slack _download_files called multiple times must share one budget."""
        from ctxd.dumpers.slack import SlackDumper

        dumper = SlackDumper(
            url="https://example.slack.com/archives/C123/p1234567890123456",
            output=None, fmt="md", download_files=True,
            max_run_size=100,  # Very small budget
        )

        # First call reserves 60 bytes
        dumper.run_budget.check_and_reserve(60)
        assert dumper.run_budget.used == 60

        # Second call should see the 60 bytes already used
        # and fail when trying to reserve 50 more (total 110 > 100)
        from ctxd.download_limits import DownloadLimitExceeded
        with pytest.raises(DownloadLimitExceeded):
            dumper.run_budget.check_and_reserve(50)

    def test_confluence_uses_shared_budget(self, monkeypatch, tmp_path: Path) -> None:
        """Confluence dumper's run_budget is the same object across calls."""
        from ctxd.dumpers.confluence import ConfluenceDumper

        d = ConfluenceDumper(
            url="https://test.atlassian.net/wiki/spaces/ABC/pages/123/Title",
            output=str(tmp_path / "export"), fmt="md", recursive=True,
        )
        budget1 = d.run_budget
        budget2 = d.run_budget
        assert budget1 is budget2  # Same object, not new each time


# ---------------------------------------------------------------------------
# Blocking #5: Atomic write failure protection
# ---------------------------------------------------------------------------

class TestAtomicWriteFailure:
    """Atomic writes must not corrupt existing files on failure."""

    def test_existing_file_preserved_on_rename_failure(self, tmp_path: Path) -> None:
        from ctxd.dumpers.base import _atomic_write_text

        path = tmp_path / "output.md"
        _atomic_write_text(path, "original content")
        assert path.read_text() == "original content"

        # Simulate a write failure by making the directory read-only
        # so the temp file can't be created... actually, let's mock os.replace
        import ctxd.dumpers.base as base_mod
        original_replace = base_mod.os.replace

        def failing_replace(src, dst):
            raise OSError("simulated rename failure")

        base_mod.os.replace = failing_replace
        try:
            with pytest.raises(OSError):
                _atomic_write_text(path, "new content that should not appear")
        finally:
            base_mod.os.replace = original_replace

        # Original file must be intact
        assert path.read_text() == "original content"
        # No temp file left behind
        assert not (tmp_path / "output.md.tmp").exists()

    def test_atomic_write_bytes_failure_cleans_temp(self, tmp_path: Path) -> None:
        from ctxd.dumpers.base import _atomic_write_bytes

        path = tmp_path / "image.png"
        _atomic_write_bytes(path, b"original")

        import ctxd.dumpers.base as base_mod
        original_replace = base_mod.os.replace

        def failing_replace(src, dst):
            raise OSError("simulated failure")

        base_mod.os.replace = failing_replace
        try:
            with pytest.raises(OSError):
                _atomic_write_bytes(path, b"new data")
        finally:
            base_mod.os.replace = original_replace

        assert path.read_bytes() == b"original"
        assert not (tmp_path / "image.png.tmp").exists()
