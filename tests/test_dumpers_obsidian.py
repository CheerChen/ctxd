"""Integration tests for --obsidian mode on Confluence and Jira dumpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _isolate_auth_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from ctxd import auth

    auth._reset_cache_for_tests()
    monkeypatch.setattr(auth, "CONFIG_PATH", Path("/nonexistent/ctxd-test/config"))
    monkeypatch.delenv("ATTACHMENTS_DIR", raising=False)


def _make_confluence_dumper(tmp_path: Path, *, output: str | None, auto: bool):
    from ctxd.confluence.api_client import ConfluenceClient
    from ctxd.dumpers.confluence import ConfluenceDumper

    dumper = ConfluenceDumper(
        url="https://example.atlassian.net/wiki/spaces/TEST/pages/12345/Design",
        output=output,
        fmt="md",
        quiet=True,
        obsidian_mode=True,
        obsidian_auto_output=auto,
    )
    client = ConfluenceClient(
        base_url="https://example.atlassian.net", email="x@x", api_token="t"
    )
    client._space_cache["98765"] = "Test Space"
    client._user_cache["acc-author"] = "Author Person"
    dumper.client = client
    dumper.validate_auth = lambda: None  # type: ignore[method-assign]
    return dumper, client


def _stub_page(page_id: str = "12345", title: str = "Design Doc", body_html: str = "<p>hello</p>") -> dict:
    return {
        "id": page_id,
        "title": title,
        "spaceId": "98765",
        "authorId": "acc-author",
        "createdAt": "2026-03-02T04:15:22Z",
        "version": {"createdAt": "2026-04-16T07:23:11Z"},
        "_links": {"webui": f"/spaces/TEST/pages/{page_id}/{title}"},
        "body": {"storage": {"value": body_html}},
    }


def test_confluence_obsidian_writes_frontmatter_and_body(tmp_path: Path) -> None:
    output_file = tmp_path / "vault" / "design.md"
    dumper, client = _make_confluence_dumper(tmp_path, output=str(output_file), auto=False)

    page = _stub_page()
    client.get_page = MagicMock(return_value=page)
    client.get_attachments = MagicMock(return_value=[])
    client.get_inline_comments = MagicMock(return_value=[])
    client.get_footer_comments = MagicMock(return_value=[])

    dumper.dump()

    assert output_file.exists()
    content = output_file.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert "confluence_url: https://example.atlassian.net/wiki/spaces/TEST/pages/12345/Design\n" in content
    assert "confluence_title: Design Doc\n" in content
    assert "\n---\n" in content  # frontmatter closing
    assert "# Design Doc\n" in content
    assert "## Metadata" in content
    assert "hello" in content


def test_confluence_obsidian_auto_output_uses_title(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    dumper, client = _make_confluence_dumper(tmp_path, output=None, auto=True)

    page = _stub_page(title="[Draft] Masking | Plan")
    client.get_page = MagicMock(return_value=page)
    client.get_attachments = MagicMock(return_value=[])
    client.get_inline_comments = MagicMock(return_value=[])
    client.get_footer_comments = MagicMock(return_value=[])

    dumper.dump()

    expected = tmp_path / "Draft Masking Plan.md"
    assert expected.exists(), f"expected note at {expected}, got {list(tmp_path.iterdir())}"


def test_confluence_obsidian_downloads_referenced_images(tmp_path: Path) -> None:
    output_file = tmp_path / "note.md"
    dumper, client = _make_confluence_dumper(tmp_path, output=str(output_file), auto=False)

    body_html = '<p>before</p><ac:image><ri:attachment ri:filename="diagram.png"/></ac:image><p>after</p>'
    page = _stub_page(body_html=body_html)
    client.get_page = MagicMock(return_value=page)
    client.get_attachments = MagicMock(return_value=[
        {"title": "diagram.png", "fileId": "uuid-diagram", "pageId": "12345"},
        {"title": "unused.pdf", "fileId": "uuid-unused", "pageId": "12345"},
    ])
    client.get_inline_comments = MagicMock(return_value=[])
    client.get_footer_comments = MagicMock(return_value=[])
    client.download_attachment = MagicMock(return_value=b"PNGDATA")

    dumper.dump()

    assets_dir = tmp_path / "assets"
    assert (assets_dir / "12345-diagram.png").read_bytes() == b"PNGDATA"
    assert not (assets_dir / "12345-unused.pdf").exists()

    content = output_file.read_text(encoding="utf-8")
    assert "assets/12345-diagram.png" in content


def test_confluence_obsidian_cleans_stale_attachments(tmp_path: Path) -> None:
    output_file = tmp_path / "note.md"
    dumper, client = _make_confluence_dumper(tmp_path, output=str(output_file), auto=False)

    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    (assets_dir / "12345-removed.png").write_bytes(b"stale")
    (assets_dir / "99999-from-other-page.png").write_bytes(b"other-page")

    body_html = '<p><ac:image><ri:attachment ri:filename="kept.png"/></ac:image></p>'
    page = _stub_page(body_html=body_html)
    client.get_page = MagicMock(return_value=page)
    client.get_attachments = MagicMock(return_value=[
        {"title": "kept.png", "fileId": "uuid-kept", "pageId": "12345"},
    ])
    client.get_inline_comments = MagicMock(return_value=[])
    client.get_footer_comments = MagicMock(return_value=[])
    client.download_attachment = MagicMock(return_value=b"NEW")

    dumper.dump()

    assert (assets_dir / "12345-kept.png").exists()
    assert not (assets_dir / "12345-removed.png").exists()
    assert (assets_dir / "99999-from-other-page.png").exists()


def test_confluence_obsidian_attachments_go_to_vault_root(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    note_dir = vault / "folder" / "sub"
    note_dir.mkdir(parents=True)
    output_file = note_dir / "note.md"

    dumper, client = _make_confluence_dumper(tmp_path, output=str(output_file), auto=False)

    body_html = '<p><ac:image><ri:attachment ri:filename="diagram.png"/></ac:image></p>'
    page = _stub_page(body_html=body_html)
    client.get_page = MagicMock(return_value=page)
    client.get_attachments = MagicMock(return_value=[
        {"title": "diagram.png", "fileId": "uuid-diagram", "pageId": "12345"},
    ])
    client.get_inline_comments = MagicMock(return_value=[])
    client.get_footer_comments = MagicMock(return_value=[])
    client.download_attachment = MagicMock(return_value=b"PNG")

    dumper.dump()

    # Attachments must land at vault root, NOT next to the note
    assert (vault / "assets" / "12345-diagram.png").read_bytes() == b"PNG"
    assert not (note_dir / "assets").exists()


def test_confluence_obsidian_all_attachments(tmp_path: Path) -> None:
    output_file = tmp_path / "note.md"
    dumper, client = _make_confluence_dumper(tmp_path, output=str(output_file), auto=False)
    dumper.all_attachments = True

    page = _stub_page(body_html="<p>no images</p>")
    client.get_page = MagicMock(return_value=page)
    client.get_attachments = MagicMock(return_value=[
        {"title": "report.pdf", "fileId": "uuid-report", "pageId": "12345"},
    ])
    client.get_inline_comments = MagicMock(return_value=[])
    client.get_footer_comments = MagicMock(return_value=[])
    client.download_attachment = MagicMock(return_value=b"PDF")

    dumper.dump()

    assert (tmp_path / "assets" / "12345-report.pdf").read_bytes() == b"PDF"


def _make_jira_dumper(*, output: str | None, auto: bool):
    from ctxd.dumpers.jira import JiraDumper
    from ctxd.jira.api_client import JiraClient

    dumper = JiraDumper(
        url="https://example.atlassian.net/browse/PROJ-1",
        output=output,
        fmt="md",
        quiet=True,
        obsidian_mode=True,
        obsidian_auto_output=auto,
    )
    client = JiraClient(
        base_url="https://example.atlassian.net", email="x@x", api_token="t"
    )
    dumper.client = client
    dumper.validate_auth = lambda: None  # type: ignore[method-assign]
    return dumper, client


def _jira_issue() -> dict:
    return {
        "key": "PROJ-1",
        "fields": {
            "summary": "Investigate masking",
            "status": {"name": "In Progress"},
            "priority": {"name": "High"},
            "issuetype": {"name": "Task"},
            "assignee": {"displayName": "Alice"},
            "reporter": {"displayName": "Bob"},
            "labels": [],
            "components": [],
            "created": "2026-03-02",
            "updated": "2026-04-16",
            "description": "Plain text description.",
            "subtasks": [],
            "issuelinks": [],
        },
        "renderedFields": {"description": "", "comment": {"comments": []}},
        "names": {},
    }


def test_jira_obsidian_writes_frontmatter_and_body(tmp_path: Path) -> None:
    output_file = tmp_path / "issue.md"
    dumper, client = _make_jira_dumper(output=str(output_file), auto=False)

    client.get_issue = MagicMock(return_value=_jira_issue())
    client.get_comments = MagicMock(return_value=[])

    dumper.dump()

    content = output_file.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert "jira_url: https://example.atlassian.net/browse/PROJ-1\n" in content
    assert 'jira_title: "[PROJ-1] Investigate masking"\n' in content
    assert "\n---\n" in content  # frontmatter closing
    assert "# [PROJ-1] Investigate masking\n" in content
    assert "Plain text description." in content


def test_jira_obsidian_auto_output_uses_title(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    dumper, client = _make_jira_dumper(output=None, auto=True)

    client.get_issue = MagicMock(return_value=_jira_issue())
    client.get_comments = MagicMock(return_value=[])

    dumper.dump()

    expected = tmp_path / "PROJ-1 Investigate masking.md"
    assert expected.exists(), f"expected note at {expected}, got {list(tmp_path.iterdir())}"
