"""Effective acceptance tests for P1 blocking fixes.

Each test constructs real scenarios that would fail if the fix were
missing, rather than just checking a function returns successfully.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from ctxd.cli import main


# ---------------------------------------------------------------------------
# Test 1: --max-chars 500 -o output.md — real CLI, oversized content,
# assert file length limited, notice present, manifest truncated=1.
# ---------------------------------------------------------------------------

class TestMaxCharsFileOutput:
    def test_file_output_truncated_with_manifest(self, tmp_path: Path, monkeypatch) -> None:
        """--max-chars on file output: file is truncated, notice present,
        manifest records truncated=1."""
        from ctxd.dumpers.github_pr import GitHubPRDumper

        monkeypatch.setattr("ctxd.dumpers.github_pr.ensure_github_auth", lambda: None)
        monkeypatch.setattr("ctxd.auth.ensure_github_auth", lambda: None)

        # Generate ~10K chars of body content
        long_body = "A" * 10000
        long_diff = "diff --git a/file b/file\n+line\n" * 200  # ~10K

        def mock_run(cmd, **kw):
            s = " ".join(cmd)
            if "pr view" in s:
                return MagicMock(returncode=0, stdout=json.dumps({"title": "T", "body": long_body}), stderr="")
            if "pr diff" in s:
                return MagicMock(returncode=0, stdout=long_diff, stderr="")
            if "api" in s:
                return MagicMock(returncode=0, stdout="[]", stderr="")
            return MagicMock(returncode=0, stdout="{}", stderr="")

        monkeypatch.setattr("ctxd.dumpers.github_pr.subprocess.run", mock_run)

        out_file = tmp_path / "out.md"
        runner = CliRunner()
        result = runner.invoke(main, [
            "https://github.com/o/r/pull/1",
            "-o", str(out_file),
            "--max-chars", "500",
        ])
        assert result.exit_code == 0, f"{result.output}\n{result.exception}"

        content = out_file.read_text()
        # The final file must be at most max_chars (500) — hard cap.
        assert len(content) <= 500, f"File length {len(content)} exceeds max_chars 500"
        assert "truncated" in content
        assert "Original size:" in content

        # Manifest must record truncated=1
        manifest_file = tmp_path / "out.md.manifest.json"
        assert manifest_file.exists()
        manifest = json.loads(manifest_file.read_text())
        assert manifest.get("truncated", 0) >= 1


# ---------------------------------------------------------------------------
# Test 2: --max-file-size -1 — mock streaming response, assert positive-size
# file is downloaded successfully.
# ---------------------------------------------------------------------------

class TestMaxFileSizeUnlimited:
    def test_negative_max_file_size_allows_download(self, tmp_path: Path, monkeypatch) -> None:
        from ctxd.dumpers.slack import SlackDumper

        dumper = SlackDumper(
            url="https://example.slack.com/archives/C123/p1234567890123456",
            output=str(tmp_path / "out.md"), fmt="md", download_files=True,
            max_file_size=-1,  # Unlimited
        )
        monkeypatch.setattr(dumper, "validate_auth", lambda: None)
        monkeypatch.setattr(dumper, "token", "xoxb-test")

        # Mock session.get to return a 1000-byte file (would exceed default 50MiB? no,
        # but we verify -1 doesn't reject it)
        file_data = b"\x89PNG" + b"\x00" * 996  # 1000 bytes

        class FakeResp:
            headers = {"content-type": "image/png", "content-length": "1000"}
            def raise_for_status(self): pass
            def iter_content(self, chunk_size=8192):
                yield file_data
            def close(self): pass

        monkeypatch.setattr(dumper.session, "get", lambda url, **kw: FakeResp())

        files = [{"id": "F1", "name": "test.png", "url_private_download": "https://slack.com/files/F1/dl"}]
        dumper._download_files(files, tmp_path)

        downloaded = (tmp_path / "attachments" / "IMG_F1.png").read_bytes()
        assert downloaded == file_data


# ---------------------------------------------------------------------------
# Test 3: --max-run-size -1 — download two files, both succeed.
# ---------------------------------------------------------------------------

class TestMaxRunSizeUnlimited:
    def test_negative_max_run_size_allows_multiple_downloads(self, tmp_path: Path, monkeypatch) -> None:
        from ctxd.dumpers.slack import SlackDumper

        dumper = SlackDumper(
            url="https://example.slack.com/archives/C123/p1234567890123456",
            output=str(tmp_path / "out.md"), fmt="md", download_files=True,
            max_run_size=-1,  # Unlimited
        )
        monkeypatch.setattr(dumper, "validate_auth", lambda: None)
        monkeypatch.setattr(dumper, "token", "xoxb-test")

        file_data_1 = b"\x89PNG" + b"\x00" * 996
        file_data_2 = b"\x89PNG" + b"\x00" * 1996

        call_count = [0]
        def fake_get(url, **kw):
            call_count[0] += 1
            data = file_data_1 if call_count[0] == 1 else file_data_2
            class FakeResp:
                headers = {"content-type": "image/png", "content-length": str(len(data))}
                def raise_for_status(self): pass
                def iter_content(self, chunk_size=8192):
                    yield data
                def close(self): pass
            return FakeResp()

        monkeypatch.setattr(dumper.session, "get", fake_get)

        files1 = [{"id": "F1", "name": "a.png", "url_private_download": "https://slack.com/files/F1/dl"}]
        files2 = [{"id": "F2", "name": "b.png", "url_private_download": "https://slack.com/files/F2/dl"}]

        dumper._download_files(files1, tmp_path)
        dumper._download_files(files2, tmp_path)

        assert (tmp_path / "attachments" / "IMG_F1.png").exists()
        assert (tmp_path / "attachments" / "IMG_F2.png").exists()


# ---------------------------------------------------------------------------
# Test 4: Two _download_files() calls — real download, cumulative budget,
# second call must be skipped when budget exceeded.
# ---------------------------------------------------------------------------

class TestRunBudgetCumulative:
    def test_second_download_skipped_when_budget_exceeded(self, tmp_path: Path, monkeypatch) -> None:
        from ctxd.dumpers.slack import SlackDumper

        dumper = SlackDumper(
            url="https://example.slack.com/archives/C123/p1234567890123456",
            output=str(tmp_path / "out.md"), fmt="md", download_files=True,
            max_file_size=1000,  # Allow up to 1000 bytes per file
            max_run_size=1500,   # But only 1500 total
        )
        monkeypatch.setattr(dumper, "validate_auth", lambda: None)
        monkeypatch.setattr(dumper, "token", "xoxb-test")

        file_data_1 = b"\x00" * 1000
        file_data_2 = b"\x00" * 1000

        call_count = [0]
        def fake_get(url, **kw):
            call_count[0] += 1
            data = file_data_1 if call_count[0] == 1 else file_data_2
            class FakeResp:
                headers = {"content-type": "image/png", "content-length": str(len(data))}
                def raise_for_status(self): pass
                def iter_content(self, chunk_size=8192):
                    yield data
                def close(self): pass
            return FakeResp()

        monkeypatch.setattr(dumper.session, "get", fake_get)

        files1 = [{"id": "F1", "name": "a.png", "url_private_download": "https://slack.com/files/F1/dl"}]
        files2 = [{"id": "F2", "name": "b.png", "url_private_download": "https://slack.com/files/F2/dl"}]

        dumper._download_files(files1, tmp_path)
        assert (tmp_path / "attachments" / "IMG_F1.png").exists()

        dumper._download_files(files2, tmp_path)
        # Second file must NOT exist — budget exceeded (1000 + 1000 > 1500)
        assert not (tmp_path / "attachments" / "IMG_F2.png").exists()
        # Summary must record the skip
        assert dumper.summary.skipped >= 1


# ---------------------------------------------------------------------------
# Test 5: Cross-source recursion shares run budget — two child dumpers
# download attachments, shared budget prevents the second.
# ---------------------------------------------------------------------------

class TestRunBudgetCrossSource:
    def test_cross_source_shared_budget_via_render_with_recurse(self, tmp_path: Path, monkeypatch) -> None:
        """Call render_with_recurse() directly (the real entry point),
        capture the constructed child dumper, and assert the child's
        run_budget is the same object as the parent's — from an
        uninitialised parent state."""
        from ctxd.dumpers.slack import SlackDumper
        import ctxd.recurse as recurse_mod

        parent = SlackDumper(
            url="https://example.slack.com/archives/C123/p1234567890123456",
            output=None, fmt="md", download_files=True,
            max_run_size=100,
        )
        # Do NOT touch parent.run_budget — parent._run_budget is still None.

        # Intercept _build_dumper to capture the constructed child dumper.
        captured_children: list = []
        original_build = recurse_mod._build_dumper

        def capturing_build(url, opts):
            child = original_build(url, opts)
            captured_children.append(child)
            child.render = lambda: "child content"
            return child

        monkeypatch.setattr(recurse_mod, "_build_dumper", capturing_build)
        monkeypatch.setattr(parent, "validate_auth", lambda: None)
        monkeypatch.setattr(parent, "render", lambda: (
            "See https://example.slack.com/archives/C456/p1234567890123457"
        ))

        # Call the real entry point.
        recurse_mod.render_with_recurse(parent, depth=1)

        # At least one child was constructed.
        assert len(captured_children) >= 1
        child = captured_children[0]
        # The child's run_budget must be the exact same object as the
        # parent's — not just the opts, but the actual child dumper.
        assert child.run_budget is parent.run_budget, (
            "child.run_budget is not parent.run_budget — budget not shared"
        )

    def test_recurse_budget_shared_across_two_children(self, tmp_path: Path, monkeypatch) -> None:
        """Two child dumpers built during render_with_recurse share
        the same budget object — verified on the actual child dumpers."""
        from ctxd.dumpers.slack import SlackDumper
        import ctxd.recurse as recurse_mod

        parent = SlackDumper(
            url="https://example.slack.com/archives/C123/p1234567890123456",
            output=None, fmt="md", download_files=True,
            max_run_size=100,
        )

        captured_children: list = []
        original_build = recurse_mod._build_dumper

        def capturing_build(url, opts):
            child = original_build(url, opts)
            captured_children.append(child)
            child.render = lambda: "child content"
            return child

        monkeypatch.setattr(recurse_mod, "_build_dumper", capturing_build)
        monkeypatch.setattr(parent, "validate_auth", lambda: None)
        # Parent content contains two supported URLs.
        monkeypatch.setattr(parent, "render", lambda: (
            "https://example.slack.com/archives/C456/p1111111111111111\n"
            "https://example.slack.com/archives/C789/p2222222222222222"
        ))

        recurse_mod.render_with_recurse(parent, depth=1)

        assert len(captured_children) >= 2
        # All children's run_budget must be the same object as the parent's.
        for child in captured_children:
            assert child.run_budget is parent.run_budget, (
                "child.run_budget is not parent.run_budget"
            )
        # And they must all be the same object as each other.
        assert captured_children[0].run_budget is captured_children[1].run_budget


# ---------------------------------------------------------------------------
# Test 6: Content-Length exceeds limit AND chunk-stream mid-download
# exceeds limit — response closed, target file doesn't exist, summary
# has records.
# ---------------------------------------------------------------------------

class TestDownloadSizeEnforcement:
    def test_content_length_exceeds_limit(self, tmp_path: Path, monkeypatch) -> None:
        from ctxd.dumpers.slack import SlackDumper

        dumper = SlackDumper(
            url="https://example.slack.com/archives/C123/p1234567890123456",
            output=str(tmp_path / "out.md"), fmt="md", download_files=True,
            max_file_size=500,
        )
        monkeypatch.setattr(dumper, "validate_auth", lambda: None)
        monkeypatch.setattr(dumper, "token", "xoxb-test")

        closed = [False]
        class FakeResp:
            headers = {"content-type": "image/png", "content-length": "1000"}
            def raise_for_status(self): pass
            def iter_content(self, chunk_size=8192):
                yield b"\x00" * 1000
            def close(self):
                closed[0] = True

        monkeypatch.setattr(dumper.session, "get", lambda url, **kw: FakeResp())

        files = [{"id": "F1", "name": "big.png", "url_private_download": "https://slack.com/files/F1/dl"}]
        dumper._download_files(files, tmp_path)

        assert closed[0]  # Response was closed
        assert not (tmp_path / "attachments" / "IMG_F1.png").exists()
        assert dumper.summary.skipped >= 1

    def test_chunk_stream_mid_download_exceeds_limit(self, tmp_path: Path, monkeypatch) -> None:
        from ctxd.dumpers.slack import SlackDumper

        dumper = SlackDumper(
            url="https://example.slack.com/archives/C123/p1234567890123456",
            output=str(tmp_path / "out.md"), fmt="md", download_files=True,
            max_file_size=100,
        )
        monkeypatch.setattr(dumper, "validate_auth", lambda: None)
        monkeypatch.setattr(dumper, "token", "xoxb-test")

        closed = [False]
        class FakeResp:
            # No Content-Length header — forces streaming detection
            headers = {"content-type": "image/png"}
            def raise_for_status(self): pass
            def iter_content(self, chunk_size=8192):
                yield b"\x00" * 80   # OK so far
                yield b"\x00" * 80   # Now 160 > 100 limit
            def close(self):
                closed[0] = True

        monkeypatch.setattr(dumper.session, "get", lambda url, **kw: FakeResp())

        files = [{"id": "F1", "name": "stream.png", "url_private_download": "https://slack.com/files/F1/dl"}]
        dumper._download_files(files, tmp_path)

        assert closed[0]
        assert not (tmp_path / "attachments" / "IMG_F1.png").exists()
        assert dumper.summary.skipped >= 1
        assert any("size limit" in n for n in dumper.summary.notes)


# ---------------------------------------------------------------------------
# Test 7: Atomic write failure in compat downloader — temp file cleaned up.
# ---------------------------------------------------------------------------

class TestDownloaderTempCleanup:
    def test_downloader_cleans_temp_on_failure(self, tmp_path: Path, monkeypatch) -> None:
        from ctxd.confluence.downloader import ImageDownloader

        downloader = ImageDownloader(str(tmp_path))

        # Mock session.get to raise during streaming
        class FakeResp:
            def raise_for_status(self): pass
            def iter_content(self, chunk_size=8192):
                yield b"\x00" * 100
                raise OSError("network error mid-stream")
            def close(self): pass

        monkeypatch.setattr(downloader.session, "get", lambda url, **kw: FakeResp())

        result = downloader._download_single("https://example.com/image.png")
        assert result[1] is None  # Download failed

        # No temp file should be left behind
        temp_files = list(tmp_path.glob("*.tmp"))
        assert len(temp_files) == 0, f"Temp files left behind: {temp_files}"
        # No partial file either
        assert not (tmp_path / "image.png").exists()


# ---------------------------------------------------------------------------
# Test 8: --max-chars is a hard cap on final output length.
# ---------------------------------------------------------------------------

class TestMaxCharsHardCap:
    def test_output_never_exceeds_max_chars(self) -> None:
        """Input 1000 chars, limit 500 → final output must be <= 500."""
        from ctxd.dumpers.base import _apply_stdout_limit

        content = "line of text\n" * 80  # ~1040 chars
        result = _apply_stdout_limit(content, max_chars=500)
        assert len(result) <= 500, f"Output {len(result)} exceeds hard cap 500"
        assert "truncated" in result

    def test_hard_cap_with_code_fence(self) -> None:
        """Even with an open code fence, final output <= max_chars."""
        from ctxd.dumpers.base import _apply_stdout_limit

        # Open fence near the beginning, then lots of content
        content = "```python\n" + "x = 1\n" * 200  # ~1400 chars, fence open
        result = _apply_stdout_limit(content, max_chars=500)
        assert len(result) <= 500, f"Output {len(result)} exceeds hard cap 500"
        # Fence must be closed
        notice_idx = result.find("\n\n> [ctxd:")
        body = result[:notice_idx] if notice_idx > 0 else result
        assert body.count("```") % 2 == 0

    def test_hard_cap_with_summary_channel_file(self) -> None:
        """File truncation records 'file' in the summary note, not 'stdout'."""
        from ctxd.dumpers.base import _apply_stdout_limit
        from ctxd.summary import Summary

        summary = Summary(source="test")
        content = "x" * 2000
        result = _apply_stdout_limit(content, max_chars=500, summary=summary, channel="file")
        assert len(result) <= 500
        assert summary.truncated == 1
        assert any("file truncated" in n for n in summary.notes)
        assert not any("stdout truncated" in n for n in summary.notes)

    def test_hard_cap_with_summary_channel_stdout(self) -> None:
        """stdout truncation records 'stdout' in the summary note."""
        from ctxd.dumpers.base import _apply_stdout_limit
        from ctxd.summary import Summary

        summary = Summary(source="test")
        content = "x" * 2000
        result = _apply_stdout_limit(content, max_chars=500, summary=summary, channel="stdout")
        assert len(result) <= 500
        assert any("stdout truncated" in n for n in summary.notes)


# ---------------------------------------------------------------------------
# Test 9: --max-chars applies to Confluence directory, Confluence Obsidian,
# and Jira Obsidian file outputs.
# ---------------------------------------------------------------------------

class TestMaxCharsAllFilePaths:
    def test_confluence_directory_pages_truncated(self, tmp_path: Path, monkeypatch) -> None:
        """Confluence directory export with --max-chars: each page file
        is truncated to <= max_chars."""
        from ctxd.dumpers.confluence import ConfluenceDumper

        d = ConfluenceDumper(
            url="https://test.atlassian.net/wiki/spaces/ABC/pages/123/Root",
            output=str(tmp_path / "export"), fmt="md", recursive=True,
            max_chars=300,
        )
        monkeypatch.setattr(d, "validate_auth", lambda: None)
        monkeypatch.setattr(d, "_resolve_short_link", lambda: None)
        d.client = MagicMock()
        d.client.base_url = "https://test.atlassian.net"
        # Generate >300 chars of content
        long_html = "<p>" + "A" * 500 + "</p>"
        d.client.get_page = MagicMock(return_value={
            "id": "123", "title": "Root",
            "body": {"storage": {"value": long_html}},
        })
        d.client.get_descendants = MagicMock(return_value=[])
        d.client.get_inline_comments = MagicMock(return_value=[])
        d.client.get_footer_comments = MagicMock(return_value=[])
        d.client.get_space_name = MagicMock(return_value="SPACE")
        d.client.get_user_display_name = MagicMock(return_value="Author")
        d.client.get_attachments = MagicMock(return_value=[])

        d.dump()

        page_file = tmp_path / "export" / "123_Root" / "README.md"
        content = page_file.read_text()
        assert len(content) <= 300, f"Page file {len(content)} exceeds max_chars 300"
        assert "truncated" in content

    def test_confluence_obsidian_truncated(self, tmp_path: Path, monkeypatch) -> None:
        """Confluence Obsidian export with --max-chars: note file truncated."""
        from ctxd.dumpers.confluence import ConfluenceDumper

        d = ConfluenceDumper(
            url="https://test.atlassian.net/wiki/spaces/ABC/pages/123/Title",
            output=str(tmp_path / "note.md"), fmt="md",
            max_chars=300,
        )
        d.obsidian_mode = True
        monkeypatch.setattr(d, "validate_auth", lambda: None)
        monkeypatch.setattr(d, "_resolve_short_link", lambda: None)
        d.client = MagicMock()
        d.client.base_url = "https://test.atlassian.net"
        long_html = "<p>" + "B" * 500 + "</p>"
        d.client.get_page = MagicMock(return_value={
            "id": "123", "title": "Test",
            "body": {"storage": {"value": long_html}},
        })
        d.client.get_inline_comments = MagicMock(return_value=[])
        d.client.get_footer_comments = MagicMock(return_value=[])
        d.client.get_space_name = MagicMock(return_value="S")
        d.client.get_user_display_name = MagicMock(return_value="A")
        d.client.get_attachments = MagicMock(return_value=[])

        d.dump()

        content = (tmp_path / "note.md").read_text()
        assert len(content) <= 300, f"Obsidian note {len(content)} exceeds max_chars 300"
        assert "truncated" in content

    def test_jira_obsidian_truncated(self, tmp_path: Path, monkeypatch) -> None:
        """Jira Obsidian export with --max-chars: note file truncated."""
        from ctxd.dumpers.jira import JiraDumper

        d = JiraDumper(
            url="https://test.atlassian.net/browse/TEST-1",
            output=str(tmp_path / "note.md"), fmt="md",
            obsidian_mode=True, max_chars=300,
        )
        monkeypatch.setattr(d, "validate_auth", lambda: None)
        d.client = MagicMock()
        long_desc = "C" * 500
        d.client.get_issue = MagicMock(return_value={
            "key": "TEST-1",
            "fields": {
                "summary": "Test",
                "status": {"name": "Open"},
                "description": long_desc,
            },
            "renderedFields": {"description": f"<p>{long_desc}</p>"},
            "names": {},
        })
        d.client.get_comments = MagicMock(return_value=[])

        d.dump()

        content = (tmp_path / "note.md").read_text()
        assert len(content) <= 300, f"Jira note {len(content)} exceeds max_chars 300"
        assert "truncated" in content


# ---------------------------------------------------------------------------
# Test 10: Confluence concurrent multi-page truncation — manifest.truncated
# equals the actual number of truncated pages.
# ---------------------------------------------------------------------------

class TestConcurrentTruncationAggregation:
    def test_multi_page_truncated_count_matches(self, tmp_path: Path, monkeypatch) -> None:
        """Export 3 pages, all exceeding --max-chars.  manifest.truncated
        must equal 3 (one per page), verified after concurrent export."""
        from ctxd.dumpers.confluence import ConfluenceDumper

        d = ConfluenceDumper(
            url="https://test.atlassian.net/wiki/spaces/ABC/pages/100/Root",
            output=str(tmp_path / "export"), fmt="md", recursive=True,
            max_chars=300,
        )
        monkeypatch.setattr(d, "validate_auth", lambda: None)
        monkeypatch.setattr(d, "_resolve_short_link", lambda: None)
        d.client = MagicMock()
        d.client.base_url = "https://test.atlassian.net"

        # 3 child pages, each with >300 chars of content
        pages = []
        for i in range(3):
            pages.append({
                "id": str(200 + i),
                "title": f"Page{i}",
                "body": {"storage": {"value": f"<p>{'X' * 500}</p>"}},
            })

        d.client.get_page = MagicMock(return_value={
            "id": "100", "title": "Root",
            "body": {"storage": {"value": f"<p>{'X' * 500}</p>"}},
        })
        d.client.get_descendants = MagicMock(return_value=pages)
        d.client.get_inline_comments = MagicMock(return_value=[])
        d.client.get_footer_comments = MagicMock(return_value=[])
        d.client.get_space_name = MagicMock(return_value="SPACE")
        d.client.get_user_display_name = MagicMock(return_value="Author")
        d.client.get_attachments = MagicMock(return_value=[])

        d.dump()

        # Each page file must be truncated
        for i in range(3):
            page_file = tmp_path / "export" / f"{200 + i}_Page{i}" / "README.md"
            assert page_file.exists(), f"Page {i} file missing"
            content = page_file.read_text()
            assert len(content) <= 300, f"Page {i} file {len(content)} exceeds 300"

        # Manifest must record truncated == 4 (root + 3 children)
        manifests = list(tmp_path.glob("export/**/manifest.json")) + list(tmp_path.glob("export/**/*.manifest.json"))
        assert len(manifests) >= 1, "No manifest found"
        manifest = json.loads(manifests[0].read_text())
        assert manifest.get("truncated", 0) == 4, (
            f"Expected truncated=4 (root + 3 children), got {manifest.get('truncated')}"
        )


# ---------------------------------------------------------------------------
# Test 11: Very small --max-chars still shows a truncation marker.
# ---------------------------------------------------------------------------

class TestSmallMaxChars:
    def test_max_chars_10_shows_truncated_marker(self) -> None:
        """--max-chars 10: output <= 10 chars AND contains a truncation
        marker (ultra-short notice 'ctxd' indicator)."""
        from ctxd.dumpers.base import _apply_stdout_limit

        content = "A" * 100
        result = _apply_stdout_limit(content, max_chars=10)
        assert len(result) <= 10, f"Output {len(result)} exceeds 10"
        # Ultra-short notice "> [ctxd…]\n" is 11 chars, so limit=10
        # uses the "…" fallback.  Either way, a marker must be present.
        assert "…" in result or "ctxd" in result or "truncated" in result, (
            f"No truncation marker in result: {repr(result)}"
        )

    def test_max_chars_1_shows_marker(self) -> None:
        """--max-chars 1 must output the truncation marker (…), not the
        original content's first character."""
        from ctxd.dumpers.base import _apply_stdout_limit

        content = "A" * 100
        result = _apply_stdout_limit(content, max_chars=1)
        assert len(result) <= 1
        # Must be the ellipsis marker, not 'A' from the original content.
        assert result == "…", f"Expected '…', got {repr(result)}"

    def test_max_chars_30_shows_short_notice(self) -> None:
        """--max-chars 30 (enough for short notice): '[ctxd: truncated]'."""
        from ctxd.dumpers.base import _apply_stdout_limit

        content = "A" * 200
        result = _apply_stdout_limit(content, max_chars=30)
        assert len(result) <= 30
        assert "[ctxd: truncated]" in result

    def test_max_chars_50_shows_short_notice(self) -> None:
        """--max-chars 50 (below _MIN_FULL_NOTICE_LIMIT): short notice used."""
        from ctxd.dumpers.base import _apply_stdout_limit

        content = "A" * 200
        result = _apply_stdout_limit(content, max_chars=50)
        assert len(result) <= 50
        assert "[ctxd: truncated]" in result

    def test_max_chars_150_shows_full_notice(self) -> None:
        """--max-chars 150 (above _MIN_FULL_NOTICE_LIMIT): full notice used."""
        from ctxd.dumpers.base import _apply_stdout_limit

        content = "A" * 500
        result = _apply_stdout_limit(content, max_chars=150)
        assert len(result) <= 150
        assert "Original size:" in result
        assert "retained:" in result
