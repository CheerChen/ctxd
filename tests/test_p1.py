"""Tests for P1 features: data disclaimer, atomic writes, control char
sanitization, download size limits, and stdout truncation."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from ctxd.cli import main


# ---------------------------------------------------------------------------
# P1-4: Data disclaimer
# ---------------------------------------------------------------------------

class TestDataDisclaimer:
    """Every output must start with the 'content is data' disclaimer."""

    def test_md_output_has_html_comment_disclaimer(self, tmp_path: Path) -> None:
        from ctxd.dumpers.base import _prepend_disclaimer
        content = _prepend_disclaimer("Hello world", "md")
        assert content.startswith("<!-- ctxd:")
        assert "fetched data" in content
        assert "Hello world" in content

    def test_text_output_has_plain_disclaimer(self) -> None:
        from ctxd.dumpers.base import _prepend_disclaimer
        content = _prepend_disclaimer("Hello world", "text")
        assert content.startswith("[ctxd:")
        assert "fetched data" in content
        assert "Hello world" in content

    def test_empty_content_no_disclaimer(self) -> None:
        from ctxd.dumpers.base import _prepend_disclaimer
        assert _prepend_disclaimer("", "md") == ""


# ---------------------------------------------------------------------------
# P1-5a: Atomic writes
# ---------------------------------------------------------------------------

class TestAtomicWrites:
    """Text and bytes must be written atomically (temp + rename)."""

    def test_atomic_write_text(self, tmp_path: Path) -> None:
        from ctxd.dumpers.base import _atomic_write_text
        path = tmp_path / "output.md"
        _atomic_write_text(path, "Hello, world!")
        assert path.read_text() == "Hello, world!"
        # No temp file left behind
        assert not (tmp_path / "output.md.tmp").exists()

    def test_atomic_write_bytes(self, tmp_path: Path) -> None:
        from ctxd.dumpers.base import _atomic_write_bytes
        path = tmp_path / "image.png"
        _atomic_write_bytes(path, b"\x89PNG\r\n\x1a\n")
        assert path.read_bytes() == b"\x89PNG\r\n\x1a\n"
        assert not (tmp_path / "image.png.tmp").exists()

    def test_atomic_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        from ctxd.dumpers.base import _atomic_write_text
        path = tmp_path / "sub" / "dir" / "output.md"
        _atomic_write_text(path, "nested")
        assert path.read_text() == "nested"

    def test_manifest_written_atomically(self, tmp_path: Path) -> None:
        from ctxd.summary import Summary
        s = Summary(source="test", resources_fetched=1, resources_rendered=1, artifacts_written=1)
        manifest = s.write_manifest(tmp_path / "output.md")
        assert manifest.exists()
        data = json.loads(manifest.read_text())
        assert data["source"] == "test"
        # No temp file left
        assert not (tmp_path / "output.md.manifest.json.tmp").exists()


# ---------------------------------------------------------------------------
# P1-5b: Control character sanitization
# ---------------------------------------------------------------------------

class TestSanitizeControlChars:
    """ANSI/OSC/control characters must be removed from fetched content."""

    def test_ansi_color_codes_removed(self) -> None:
        from ctxd.sanitize import sanitize_control_chars
        text = "\x1b[31mRed text\x1b[0m normal"
        cleaned, removed = sanitize_control_chars(text)
        assert "\x1b" not in cleaned
        assert "Red text" in cleaned
        assert "normal" in cleaned
        assert removed > 0

    def test_osc_title_sequence_removed(self) -> None:
        from ctxd.sanitize import sanitize_control_chars
        text = "\x1b]0;Terminal Title\x07Hello"
        cleaned, removed = sanitize_control_chars(text)
        assert "\x1b" not in cleaned
        assert "Terminal Title" not in cleaned
        assert "Hello" in cleaned
        assert removed > 0

    def test_legitimate_whitespace_preserved(self) -> None:
        from ctxd.sanitize import sanitize_control_chars
        text = "line1\nline2\tindented\rcarriage"
        cleaned, removed = sanitize_control_chars(text)
        assert cleaned == text
        assert removed == 0

    def test_null_bytes_removed(self) -> None:
        from ctxd.sanitize import sanitize_control_chars
        text = "Hello\x00World"
        cleaned, removed = sanitize_control_chars(text)
        assert "\x00" not in cleaned
        assert "HelloWorld" in cleaned
        assert removed == 1

    def test_empty_string_unchanged(self) -> None:
        from ctxd.sanitize import sanitize_control_chars
        cleaned, removed = sanitize_control_chars("")
        assert cleaned == ""
        assert removed == 0

    def test_mixed_ansi_and_normal_text(self) -> None:
        from ctxd.sanitize import sanitize_control_chars
        text = "Normal \x1b[1;32mgreen bold\x1b[0m text\x1b]2;Win Title\x07 end"
        cleaned, removed = sanitize_control_chars(text)
        assert "\x1b" not in cleaned
        assert "Normal" in cleaned
        assert "green bold" in cleaned
        assert "text" in cleaned
        assert "end" in cleaned
        assert removed > 0


# ---------------------------------------------------------------------------
# P1-5c: Download size limits
# ---------------------------------------------------------------------------

class TestDownloadLimits:
    """Per-file and per-run size limits must be enforced."""

    def test_run_budget_tracks_usage(self) -> None:
        from ctxd.download_limits import RunBudget
        budget = RunBudget(max_run_bytes=1000)
        budget.check_and_reserve(400)
        assert budget.used == 400
        budget.check_and_reserve(500)
        assert budget.used == 900

    def test_run_budget_exceeds_raises(self) -> None:
        from ctxd.download_limits import DownloadLimitExceeded, RunBudget
        budget = RunBudget(max_run_bytes=1000)
        budget.check_and_reserve(600)
        with pytest.raises(DownloadLimitExceeded):
            budget.check_and_reserve(500)

    def test_default_limits_are_sensible(self) -> None:
        from ctxd.download_limits import DEFAULT_MAX_FILE_BYTES, DEFAULT_MAX_RUN_BYTES
        assert DEFAULT_MAX_FILE_BYTES == 50 * 1024 * 1024
        assert DEFAULT_MAX_RUN_BYTES == 500 * 1024 * 1024

    def test_run_budget_thread_safe(self) -> None:
        """Concurrent check_and_reserve calls must not lose track."""
        import threading
        from ctxd.download_limits import RunBudget
        budget = RunBudget(max_run_bytes=100000)
        errors: list[Exception] = []

        def worker():
            try:
                for _ in range(100):
                    budget.check_and_reserve(1)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        assert budget.used == 1000


# ---------------------------------------------------------------------------
# P1-6: stdout character limit
# ---------------------------------------------------------------------------

class TestStdoutLimit:
    """stdout output is truncated at 100K chars; file output is not."""

    def test_short_content_not_truncated(self) -> None:
        from ctxd.dumpers.base import _apply_stdout_limit
        content = "Hello, world!\n"
        assert _apply_stdout_limit(content) == content

    def test_long_content_truncated_at_newline(self) -> None:
        from ctxd.dumpers.base import _apply_stdout_limit
        # Create content > 100K chars with newlines
        line = "x" * 80 + "\n"
        content = line * 2000  # ~160K chars
        result = _apply_stdout_limit(content)
        assert len(result) < len(content)
        assert "truncated" in result
        assert "160" in result or str(len(content)) in result

    def test_truncation_preserves_newline_boundary(self) -> None:
        from ctxd.dumpers.base import _apply_stdout_limit
        # Content where the 100K mark is mid-line
        long_line = "y" * 200000
        content = "header\n" + long_line + "\nfooter\n"
        result = _apply_stdout_limit(content)
        assert "truncated" in result
        # Should not include the full long line
        assert len(result) < len(content)

    def test_custom_limit_via_env(self, monkeypatch) -> None:
        """The limit can be overridden via CTXD_STDOUT_MAX_CHARS."""
        import importlib
        monkeypatch.setenv("CTXD_STDOUT_MAX_CHARS", "500")
        # Re-import to pick up the env var
        import ctxd.dumpers.base
        importlib.reload(ctxd.dumpers.base)
        from ctxd.dumpers.base import _apply_stdout_limit
        content = "x" * 600
        result = _apply_stdout_limit(content)
        assert "truncated" in result
        assert "500" in result
        assert "600" in result  # original size mentioned in notice
        # The actual content portion (before the notice) must be <= 500
        notice_start = result.find("\n\n> [ctxd:")
        assert notice_start <= 500
        # Restore default
        monkeypatch.delenv("CTXD_STDOUT_MAX_CHARS", raising=False)
        importlib.reload(ctxd.dumpers.base)
