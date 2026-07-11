"""Real-path tests that exercise the full dump()/CLI pipeline.

Principle: keep real orchestration (cli.main, Dumper.dump(), render_with_recurse,
_emit_and_manifest, file/summary aggregation).  Only mock external boundaries
(auth, API client methods, subprocess.run for gh).

Validity check: if you delete _emit_and_manifest(), delete add_export_result(),
or change warn() to log(), these tests MUST fail.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from ctxd.cli import main


# ---------------------------------------------------------------------------
# 1. Confluence directory export via real dump()
# ---------------------------------------------------------------------------

class TestConfluenceDirectoryExportReal:
    """Use real ConfluenceDumper.dump() with a mock client.
    Verify page directories, manifest.json, and structured items."""

    def test_mixed_pages_real_dump(self, tmp_path: Path, monkeypatch) -> None:
        from ctxd.dumpers.confluence import ConfluenceDumper

        d = ConfluenceDumper(
            url="https://test.atlassian.net/wiki/spaces/ABC/pages/123/Root",
            output=str(tmp_path / "export"), fmt="md",
            recursive=True,
        )
        monkeypatch.setattr(d, "validate_auth", lambda: None)
        monkeypatch.setattr(d, "_resolve_short_link", lambda: None)
        d.client = MagicMock()
        d.client.base_url = "https://test.atlassian.net"

        # Root page fetch returns normal content.
        root_page = {
            "id": "123", "title": "Root",
            "body": {"storage": {"value": "<p>Root content</p>"}},
        }
        # Descendants: normal, empty, broken (no body → triggers get_page).
        descendants = [
            {"id": "1", "title": "Normal", "body": {"storage": {"value": "<p>child content</p>"}}},
            {"id": "2", "title": "Empty", "body": {"storage": {"value": ""}}},
            {"id": "3", "title": "Broken", "body": {}},
        ]
        d.client.get_descendants = MagicMock(return_value=descendants)

        # get_page is called for root (always) and for page 3 (no body).
        def mock_get_page(pid):
            if pid == "123":
                return root_page
            if pid == "3":
                raise RuntimeError("API error for page 3")
            return {"id": pid, "title": "Normal", "body": {"storage": {"value": "<p>c</p>"}}}

        d.client.get_page = mock_get_page
        d.client.get_inline_comments = MagicMock(return_value=[])
        d.client.get_footer_comments = MagicMock(return_value=[])
        d.client.get_space_name = MagicMock(return_value="SPACE")
        d.client.get_user_display_name = MagicMock(return_value="Author")
        d.client.get_attachments = MagicMock(return_value=[])

        d.dump()

        export_dir = tmp_path / "export"
        # Page directories exist for written pages (root + normal child)
        assert (export_dir / "123_Root" / "README.md").exists()
        assert (export_dir / "1_Normal" / "README.md").exists()
        # Manifest exists with structured items
        manifest_path = export_dir / "manifest.json"
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert data["source"] == "confluence"
        # 4 pages fetched: root + 3 descendants
        assert data["resources_fetched"] == 4
        # 2 rendered: root + normal child
        assert data["resources_rendered"] == 2
        assert data["artifacts_written"] == 2
        assert data["skipped"] == 1  # "Empty"
        assert data["failed"] == 1  # "Broken"
        # Structured items
        assert len(data["items"]) == 4
        items_by_id = {item["source_id"]: item for item in data["items"]}
        assert items_by_id["123"]["status"] == "written"
        assert items_by_id["1"]["status"] == "written"
        assert items_by_id["2"]["status"] == "skipped"
        assert items_by_id["2"]["reason"] == "empty page body"
        assert items_by_id["3"]["status"] == "failed"
        assert "API error" in items_by_id["3"]["reason"]


# ---------------------------------------------------------------------------
# 2. Single-file CLI via real CliRunner
# ---------------------------------------------------------------------------

class TestSingleFileCLIReal:
    """Use real CliRunner.invoke(main, [..., -o, path]).
    Only mock ensure_github_auth and subprocess.run (gh calls)."""

    def test_github_pr_single_file_with_manifest(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr("ctxd.dumpers.github_pr.ensure_github_auth",
                            lambda: None)
        monkeypatch.setattr("ctxd.auth.ensure_github_auth",
                            lambda: None)

        # Mock subprocess.run for gh CLI calls.
        # _gh_json calls: gh pr view --json title,body
        # _gh_api_paginate calls: gh api --paginate --slurp <path>
        # _fetch_unified_diff calls: gh pr diff
        def mock_run(cmd, **kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "pr view" in cmd_str:
                return MagicMock(returncode=0,
                                 stdout=json.dumps({"title": "Test PR", "body": "Test body"}),
                                 stderr="")
            if "pr diff" in cmd_str:
                return MagicMock(returncode=0, stdout="diff --git a/x b/x\n", stderr="")
            # gh api --paginate --slurp returns a JSON array
            if "api" in cmd_str:
                return MagicMock(returncode=0, stdout="[]", stderr="")
            return MagicMock(returncode=0, stdout="{}", stderr="")

        monkeypatch.setattr("ctxd.dumpers.github_pr.subprocess.run", mock_run)

        out_file = tmp_path / "pr-1.md"
        runner = CliRunner()
        result = runner.invoke(main, [
            "https://github.com/o/r/pull/1",
            "-o", str(out_file),
        ])

        assert result.exit_code == 0, f"CLI failed: {result.output}\n{result.exception}"
        assert out_file.exists()
        content = out_file.read_text()
        assert "Test PR" in content
        # Manifest exists alongside
        manifest = tmp_path / "pr-1.md.manifest.json"
        assert manifest.exists()
        data = json.loads(manifest.read_text())
        assert data["source"] == "github_pr"
        assert data["artifacts_written"] == 1
        assert data["resources_fetched"] == 1


# ---------------------------------------------------------------------------
# 3. Recursive file CLI via real CLI + render_with_recurse
# ---------------------------------------------------------------------------

class TestRecursiveCLIReal:
    """Use real CLI with --recurse-depth.  Mock network boundaries so
    parent → child → grandchild(fails) chain is exercised.  Verify
    artifacts_written == 1 and grandchild failure in manifest."""

    def test_recursive_file_with_grandchild_failure(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # Jira parent with Confluence child and GitHub grandchild (fails).
        monkeypatch.setattr("ctxd.dumpers.jira.ensure_jira_auth",
                            lambda: ("https://test.atlassian.net", "e", "t"))

        class FakeJiraClient:
            def __init__(self, base_url="", email="", api_token=""):
                pass
            def get_issue(self, key):
                return {
                    "key": key,
                    "fields": {
                        "summary": "Parent issue",
                        "status": {"name": "Open"},
                        "description": "See https://test.atlassian.net/wiki/spaces/T/pages/999/Child",
                    },
                    "renderedFields": {
                        "description": '<p>See <a href="https://test.atlassian.net/wiki/spaces/T/pages/999/Child">Child</a></p>',
                    },
                    "names": {},
                }
            def get_comments(self, key):
                return []

        monkeypatch.setattr("ctxd.dumpers.jira.JiraClient", FakeJiraClient)

        # Mock Confluence auth + client for the child
        monkeypatch.setattr("ctxd.dumpers.confluence.ensure_confluence_auth",
                            lambda: ("https://test.atlassian.net", "e", "t"))

        class FakeConfluenceClient:
            base_url = "https://test.atlassian.net"
            def __init__(self, base_url="", email="", api_token=""):
                pass
            def get_page(self, pid):
                return {
                    "id": pid, "title": "Child Page",
                    "body": {"storage": {"value": "<p>See https://github.com/o/r/pull/42</p>"}},
                }
            def get_inline_comments(self, pid): return []
            def get_footer_comments(self, pid): return []
            def get_space_name(self, sid): return "SPACE"
            def get_user_display_name(self, uid): return "Author"
            def get_attachments(self, pid): return []

        monkeypatch.setattr("ctxd.dumpers.confluence.ConfluenceClient", FakeConfluenceClient)

        # GitHub grandchild fails
        monkeypatch.setattr("ctxd.dumpers.github_pr.ensure_github_auth",
                            lambda: None)
        monkeypatch.setattr("ctxd.auth.ensure_github_auth",
                            lambda: None)

        def gh_fail(cmd, **kwargs):
            return MagicMock(returncode=1, stdout="", stderr="rate limited")

        monkeypatch.setattr("ctxd.dumpers.github_pr.subprocess.run", gh_fail)

        out_file = tmp_path / "recursive.md"
        runner = CliRunner()
        result = runner.invoke(main, [
            "https://test.atlassian.net/browse/PARENT-1",
            "--recurse-depth", "2",
            "-o", str(out_file),
        ])

        assert result.exit_code == 0, f"CLI failed: {result.output}\n{result.exception}"
        assert out_file.exists()
        content = out_file.read_text()
        assert "Parent issue" in content
        assert "Child Page" in content

        manifest = tmp_path / "recursive.md.manifest.json"
        assert manifest.exists()
        data = json.loads(manifest.read_text())
        # 2 resources rendered (parent Jira + child Confluence), 1 failed (GitHub)
        assert data["resources_rendered"] >= 2
        assert data["failed"] >= 1
        # All content embedded into ONE artifact
        assert data["artifacts_written"] == 1
        # Grandchild failure recorded in notes
        assert any("github.com" in note.lower() or "rate limited" in note
                    for note in data["notes"])
