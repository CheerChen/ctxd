"""Integration tests for summary accuracy across export modes.

Covers the gaps identified in review:
- Mixed-page Confluence directory export (written + skipped + failed)
- Depth-2 recursion summary aggregation
- Warning ↔ summary consistency (failed count matches warnings)
- Output mode matrix: stdout, single-file, recurse-file manifest generation
- Confluence page tests use tmp_path instead of hardcoded /tmp/test
- Concurrency: parallel_map workers return ExportResult, main thread aggregates
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ctxd.concurrency import configure, parallel_map
from ctxd.summary import ExportResult, PageStatus, Summary


# ---------------------------------------------------------------------------
# Confluence mixed-page directory export
# ---------------------------------------------------------------------------

class TestConfluenceMixedExport:
    """Verify parallel_map + add_export_result aggregation logic with
    real threads.

    This is a concurrency unit test — it does NOT call dump() or verify
    manifest generation.  For the real dump() → manifest path, see
    ``test_real_paths.py::TestConfluenceDirectoryExportReal``.
    """

    def test_mixed_pages_aggregation_with_threads(self, tmp_path: Path) -> None:
        from ctxd.dumpers.confluence import ConfluenceDumper

        dumper = ConfluenceDumper(
            url="https://test.atlassian.net/wiki/spaces/ABC/pages/123/title",
            output=str(tmp_path / "export"), fmt="md",
        )
        dumper.client = MagicMock()
        dumper.client.base_url = "https://test.atlassian.net"

        pages = [
            {"id": "1", "title": "Normal", "body": {"storage": {"value": "<p>content</p>"}}},
            {"id": "2", "title": "Empty", "body": {"storage": {"value": ""}}},
            {"id": "3", "title": "Broken", "body": {}},  # no body → triggers get_page
        ]

        def mock_get_page(pid):
            if pid == "3":
                raise RuntimeError("API error for page 3")
            return {"id": pid, "title": "Normal", "body": {"storage": {"value": "<p>content</p>"}}}

        dumper.client.get_page = mock_get_page
        dumper.client.get_inline_comments = MagicMock(return_value=[])
        dumper.client.get_footer_comments = MagicMock(return_value=[])
        dumper.client.get_space_name = MagicMock(return_value="SPACE")
        dumper.client.get_user_display_name = MagicMock(return_value="Author")

        output_dir = tmp_path / "export"
        output_dir.mkdir(parents=True, exist_ok=True)

        pool = {}
        lock = threading.Lock()
        # Use parallel_map with concurrency to verify thread-safety.
        configure(max_concurrency=3)
        results = parallel_map(
            lambda p: dumper._export_page(p, output_dir, pool, lock),
            pages,
        )

        # Workers return ExportResult; main thread aggregates.
        assert all(isinstance(r, ExportResult) for r in results)
        statuses = [r.status for r in results]
        assert statuses == [PageStatus.WRITTEN, PageStatus.SKIPPED, PageStatus.FAILED]

        # Aggregate in main thread (simulating dump()).
        summary = Summary(source="confluence")
        for r in results:
            summary.add_export_result(r)
        summary.resources_fetched = len(pages)

        assert summary.resources_rendered == 1
        assert summary.skipped == 1
        assert summary.failed == 1
        assert len(summary.items) == 3

        items_by_id = {item.source_id: item for item in summary.items}
        assert items_by_id["1"].status == "written"
        assert items_by_id["1"].title == "Normal"
        assert items_by_id["2"].status == "skipped"
        assert items_by_id["2"].reason == "empty page body"
        assert items_by_id["3"].status == "failed"
        assert "API error" in items_by_id["3"].reason


# ---------------------------------------------------------------------------
# Concurrency: parallel_map does not lose counts
# ---------------------------------------------------------------------------

class TestConcurrencyNoRace:
    """With real threads and many pages, add_export_result in the main
    thread must produce exact counts (no lost increments)."""

    def test_many_pages_exact_counts(self, tmp_path: Path) -> None:
        from ctxd.dumpers.confluence import ConfluenceDumper

        dumper = ConfluenceDumper(
            url="https://test.atlassian.net/wiki/spaces/ABC/pages/123/title",
            output=str(tmp_path / "export"), fmt="md",
        )
        dumper.client = MagicMock()
        dumper.client.base_url = "https://test.atlassian.net"
        dumper.client.get_page = MagicMock(
            return_value={"id": "x", "title": "X", "body": {"storage": {"value": "<p>c</p>"}}}
        )
        dumper.client.get_inline_comments = MagicMock(return_value=[])
        dumper.client.get_footer_comments = MagicMock(return_value=[])
        dumper.client.get_space_name = MagicMock(return_value="S")
        dumper.client.get_user_display_name = MagicMock(return_value="A")

        output_dir = tmp_path / "export"
        output_dir.mkdir(parents=True, exist_ok=True)

        # 20 pages, all written successfully.
        pages = [
            {"id": str(i), "title": f"Page{i}", "body": {"storage": {"value": "<p>c</p>"}}}
            for i in range(20)
        ]
        configure(max_concurrency=5)
        results = parallel_map(
            lambda p: dumper._export_page(p, output_dir, {}, threading.Lock()),
            pages,
        )

        summary = Summary(source="confluence")
        for r in results:
            summary.add_export_result(r)
        summary.resources_fetched = len(pages)

        assert summary.resources_rendered == 20
        assert summary.failed == 0
        assert summary.skipped == 0
        assert len(summary.items) == 20


# ---------------------------------------------------------------------------
# Depth-2 recursion summary aggregation
# ---------------------------------------------------------------------------

class TestDepth2Aggregation:
    """At depth 2, grandchild failures must propagate to the root summary."""

    def test_depth2_grandchild_failure_propagates(self, monkeypatch) -> None:
        from ctxd.recurse import render_with_recurse

        parent_url = "https://app.slack.com/client/T/C/thread/C-123.456"
        child_url = "https://site.atlassian.net/browse/PROJ-1"
        grandchild_url = "https://github.com/owner/repo/pull/42"

        parent_content = f"See {child_url}\n"
        child_content = f"Issue references {grandchild_url}\n"

        class FakeDumper:
            def __init__(self, url, content="content\n", fail=None):
                self.url = url
                self.output = None
                self.fmt = "md"
                self.quiet = True
                self.verbose = False
                self.summary = Summary()
                self._content = content
                self._fail = fail

            def render(self):
                if self._fail:
                    raise self._fail
                return self._content

            def log(self, msg): pass

        dumper = FakeDumper(url=parent_url, content=parent_content)

        def factory(url, opts):
            if url == child_url:
                return FakeDumper(url=url, content=child_content)
            return FakeDumper(url=url, fail=RuntimeError("grandchild boom"))

        monkeypatch.setattr("ctxd.recurse._build_dumper", factory)
        render_with_recurse(dumper, depth=2)

        # 2 rendered (parent + child), 1 failed (grandchild never fetched)
        assert dumper.summary.resources_rendered == 2
        assert dumper.summary.resources_fetched == 2
        assert dumper.summary.failed == 1
        # Artifacts not incremented by recursion (CLI sets it).
        assert dumper.summary.artifacts_written == 0
        assert any("grandchild" in note for note in dumper.summary.notes)

    def test_depth2_grandchild_truncation_propagates(self, monkeypatch) -> None:
        from ctxd.recurse import MAX_CHILDREN_PER_LEVEL, render_with_recurse

        parent_url = "https://app.slack.com/client/T/C/thread/C-123.456"
        child_url = "https://site.atlassian.net/browse/PROJ-1"
        grandchild_urls = [
            f"https://github.com/owner/repo/pull/{i}"
            for i in range(MAX_CHILDREN_PER_LEVEL + 2)
        ]
        parent_content = f"See {child_url}\n"
        child_content = "See " + " ".join(grandchild_urls) + "\n"

        class FakeDumper:
            def __init__(self, url, content="content\n", fail=None):
                self.url = url
                self.output = None
                self.fmt = "md"
                self.quiet = True
                self.verbose = False
                self.summary = Summary()
                self._content = content
                self._fail = fail

            def render(self):
                if self._fail:
                    raise self._fail
                return self._content

            def log(self, msg): pass

        dumper = FakeDumper(url=parent_url, content=parent_content)

        def factory(url, opts):
            if url == child_url:
                return FakeDumper(url=url, content=child_content)
            return FakeDumper(url=url, content=f"content {url}\n")

        monkeypatch.setattr("ctxd.recurse._build_dumper", factory)
        render_with_recurse(dumper, depth=2)

        assert dumper.summary.truncated >= 2


# ---------------------------------------------------------------------------
# Warning ↔ summary consistency
# ---------------------------------------------------------------------------

class TestWarningSummaryConsistency:
    """When a warning is emitted for data loss, the summary must reflect it."""

    def test_github_api_failure_increases_failed(self, capsys: pytest.CaptureFixture) -> None:
        from ctxd.dumpers.github_pr import GitHubPRDumper

        d = GitHubPRDumper(
            url="https://github.com/o/r/pull/1",
            output=None, fmt="md", quiet=True,
        )
        d.owner = "o"
        d.repo = "r"
        d.pr_number = "1"

        proc = MagicMock(returncode=1, stderr="rate limited", stdout="")
        with patch("ctxd.dumpers.github_pr.subprocess.run", return_value=proc):
            d._gh_api_paginate("/repos/o/r/issues/1/comments")

        captured = capsys.readouterr()
        assert "GitHub API call failed" in captured.err
        assert d.summary.failed == 1
        assert any("rate limited" in note for note in d.summary.notes)

    def test_github_diff_failure_increases_failed(self, capsys: pytest.CaptureFixture) -> None:
        from ctxd.dumpers.github_pr import GitHubPRDumper

        d = GitHubPRDumper(
            url="https://github.com/o/r/pull/1",
            output=None, fmt="md", quiet=True,
        )
        d.owner = "o"
        d.repo = "r"
        d.pr_number = "1"

        proc = MagicMock(returncode=1, stderr="network error", stdout="")
        with patch("ctxd.dumpers.github_pr.subprocess.run", return_value=proc):
            d._fetch_unified_diff()

        captured = capsys.readouterr()
        assert "PR diff fetch failed" in captured.err
        assert d.summary.failed == 1

    def test_slack_download_failure_increases_failed(
        self, capsys: pytest.CaptureFixture, tmp_path: Path
    ) -> None:
        from ctxd.dumpers.slack import SlackDumper

        d = SlackDumper(
            url="https://app.slack.com/client/T/C123/thread/C123-1234567890.123456",
            output=None, fmt="md", quiet=True,
        )
        d.token = "xoxp-fake"
        files = [{"url_private_download": "https://files.slack.com/x", "name": "test.png", "id": "F1"}]
        with patch.object(d.session, "get", side_effect=RuntimeError("network error")):
            d._download_files(files, tmp_path)

        captured = capsys.readouterr()
        assert "Failed to download test.png" in captured.err
        assert d.summary.failed == 1

    def test_slack_no_url_file_increases_skipped(
        self, capsys: pytest.CaptureFixture, tmp_path: Path
    ) -> None:
        """Never-silent: Slack file with no download URL must warn + count."""
        from ctxd.dumpers.slack import SlackDumper

        d = SlackDumper(
            url="https://app.slack.com/client/T/C123/thread/C123-1234567890.123456",
            output=None, fmt="md", quiet=True,
        )
        d.token = "xoxp-fake"
        files = [{"name": "orphan.txt", "id": "F2"}]  # no url fields
        d._download_files(files, tmp_path)

        captured = capsys.readouterr()
        assert "no download URL" in captured.err
        assert d.summary.skipped == 1
        assert any("orphan.txt" in note for note in d.summary.notes)


# ---------------------------------------------------------------------------
# Output mode matrix: manifest generation
# ---------------------------------------------------------------------------

class TestManifestOutputModes:
    """Summary.write_manifest() unit tests — verify manifest file format
    and placement logic.

    These are unit tests for the Summary dataclass, NOT end-to-end tests.
    For the real dumper → manifest path, see ``test_real_paths.py``.
    """

    def test_single_file_manifest(self, tmp_path: Path) -> None:
        s = Summary(source="github_pr", resources_fetched=1, resources_rendered=1, artifacts_written=1)
        out_file = tmp_path / "pr-1.md"
        out_file.write_text("content", encoding="utf-8")

        manifest_path = s.write_manifest(out_file)
        assert manifest_path.exists()
        assert manifest_path.name == "pr-1.md.manifest.json"
        data = json.loads(manifest_path.read_text())
        assert data["source"] == "github_pr"
        assert data["artifacts_written"] == 1

    def test_directory_manifest(self, tmp_path: Path) -> None:
        s = Summary(source="confluence", resources_fetched=5, resources_rendered=3, skipped=1, failed=1)
        out_dir = tmp_path / "export"
        out_dir.mkdir()

        manifest_path = s.write_manifest(out_dir)
        assert manifest_path == out_dir / "manifest.json"
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert data["resources_fetched"] == 5
        assert data["skipped"] == 1

    def test_manifest_contains_items(self, tmp_path: Path) -> None:
        s = Summary(source="confluence", resources_fetched=3)
        s.add_item(source_id="1", status="written", title="Page 1")
        s.add_item(source_id="2", status="skipped", title="Page 2", reason="empty")
        s.add_item(source_id="3", status="failed", title="Page 3", reason="API error")

        manifest_path = s.write_manifest(tmp_path)
        data = json.loads(manifest_path.read_text())
        assert len(data["items"]) == 3
        items_by_id = {item["source_id"]: item for item in data["items"]}
        assert items_by_id["2"]["reason"] == "empty"
        assert items_by_id["3"]["reason"] == "API error"

    def test_emit_and_manifest_with_explicit_path(self, tmp_path: Path) -> None:
        """_emit_and_manifest with explicit manifest_path writes manifest
        even when self.output is None (Obsidian -O auto-naming)."""
        from ctxd.dumpers.jira import JiraDumper

        d = JiraDumper(
            url="https://test.atlassian.net/browse/PROJ-1",
            output=None, fmt="md", quiet=True,
        )
        d.summary = Summary(source="jira", resources_fetched=1, resources_rendered=1, artifacts_written=1)
        out_file = tmp_path / "jira-PROJ-1.md"
        out_file.write_text("content", encoding="utf-8")

        d._emit_and_manifest(manifest_path=out_file)
        manifest = tmp_path / "jira-PROJ-1.md.manifest.json"
        assert manifest.exists()
        data = json.loads(manifest.read_text())
        assert data["source"] == "jira"


# ---------------------------------------------------------------------------
# Confluence page tests with tmp_path (replaces hardcoded /tmp/test)
# ---------------------------------------------------------------------------

class TestConfluencePageStatusTmpPath:
    """Replaces the hardcoded /tmp/test tests with proper tmp_path isolation."""

    def test_empty_page_returns_skipped(self, tmp_path: Path) -> None:
        from ctxd.dumpers.confluence import ConfluenceDumper

        d = ConfluenceDumper(
            url="https://test.atlassian.net/wiki/spaces/ABC/pages/123/title",
            output=str(tmp_path / "export"), fmt="md",
        )
        d.client = MagicMock()
        page_data = {"id": "123", "title": "Empty", "body": {"storage": {"value": ""}}}
        result = d._export_page(page_data, tmp_path / "export", {}, threading.Lock())
        assert result.status is PageStatus.SKIPPED
        assert result.reason == "empty page body"

    def test_failed_page_returns_failed(self, tmp_path: Path) -> None:
        from ctxd.dumpers.confluence import ConfluenceDumper

        d = ConfluenceDumper(
            url="https://test.atlassian.net/wiki/spaces/ABC/pages/123/title",
            output=str(tmp_path / "export"), fmt="md",
        )
        d.client = MagicMock()
        d.client.get_page.side_effect = RuntimeError("API error")
        page_data = {"id": "123", "title": "Test", "body": {}}
        result = d._export_page(page_data, tmp_path / "export", {}, threading.Lock())
        assert result.status is PageStatus.FAILED
        assert "API error" in result.reason

    def test_written_page_returns_written(self, tmp_path: Path) -> None:
        from ctxd.dumpers.confluence import ConfluenceDumper

        d = ConfluenceDumper(
            url="https://test.atlassian.net/wiki/spaces/ABC/pages/123/title",
            output=str(tmp_path / "export"), fmt="md",
        )
        d.client = MagicMock()
        d.client.base_url = "https://test.atlassian.net"
        d.client.get_inline_comments = MagicMock(return_value=[])
        d.client.get_footer_comments = MagicMock(return_value=[])
        d.client.get_space_name = MagicMock(return_value="SPACE")
        d.client.get_user_display_name = MagicMock(return_value="Author")

        page_data = {"id": "123", "title": "Test", "body": {"storage": {"value": "<p>content</p>"}}}
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        result = d._export_page(page_data, export_dir, {}, threading.Lock())
        assert result.status is PageStatus.WRITTEN
        assert (export_dir / "123_Test" / "README.md").exists()


# ---------------------------------------------------------------------------
# Obsidian -O auto-naming manifest generation (阻断#3)
# ---------------------------------------------------------------------------

class TestObsidianAutoNameManifest:
    """Obsidian -O auto-naming must write a manifest even when
    self.output is None (the output path is resolved locally)."""

    def test_jira_obsidian_auto_name_writes_manifest(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from ctxd.dumpers.jira import JiraDumper

        d = JiraDumper(
            url="https://test.atlassian.net/browse/PROJ-1",
            output=None, fmt="md", quiet=True,
            obsidian_mode=True, obsidian_auto_output=True,
        )
        d.client = MagicMock()
        d.client.get_issue = MagicMock(return_value={
            "key": "PROJ-1", "fields": {"summary": "Test"}, "renderedFields": {}, "names": {},
        })
        d.client.get_comments = MagicMock(return_value=[])
        # Bypass validate_auth to avoid real API client construction.
        monkeypatch.setattr(d, "validate_auth", lambda: None)

        monkeypatch.chdir(tmp_path)
        d.dump()

        # The note file should exist
        notes = list(tmp_path.glob("*.md"))
        assert len(notes) == 1
        # The manifest must exist alongside it
        manifests = list(tmp_path.glob("*.md.manifest.json"))
        assert len(manifests) == 1, f"Expected 1 manifest, found {manifests}"
        data = json.loads(manifests[0].read_text())
        assert data["source"] == "jira"
        assert data["artifacts_written"] == 1

    def test_confluence_obsidian_auto_name_writes_manifest(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from ctxd.dumpers.confluence import ConfluenceDumper

        d = ConfluenceDumper(
            url="https://test.atlassian.net/wiki/spaces/ABC/pages/123/title",
            output=None, fmt="md", quiet=True,
        )
        d.obsidian_mode = True
        d.client = MagicMock()
        d.client.base_url = "https://test.atlassian.net"
        d.client.get_page = MagicMock(return_value={
            "id": "123", "title": "Test Page",
            "body": {"storage": {"value": "<p>content</p>"}},
        })
        d.client.get_attachments = MagicMock(return_value=[])
        d.client.get_inline_comments = MagicMock(return_value=[])
        d.client.get_footer_comments = MagicMock(return_value=[])
        d.client.get_space_name = MagicMock(return_value="SPACE")
        d.client.get_user_display_name = MagicMock(return_value="Author")
        # Bypass validate_auth and _resolve_short_link to avoid real API calls.
        monkeypatch.setattr(d, "validate_auth", lambda: None)
        monkeypatch.setattr(d, "_resolve_short_link", lambda: None)

        monkeypatch.chdir(tmp_path)
        d.dump()

        notes = list(tmp_path.glob("*.md"))
        assert len(notes) == 1
        manifests = list(tmp_path.glob("*.md.manifest.json"))
        assert len(manifests) == 1, f"Expected 1 manifest, found {manifests}"
        data = json.loads(manifests[0].read_text())
        assert data["source"] == "confluence"
        assert data["artifacts_written"] == 1
