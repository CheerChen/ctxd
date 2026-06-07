"""Tests for the obsidian helper module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ctxd.obsidian import (
    AttachmentRef,
    _yaml_escape,
    build_attachment_refs,
    find_vault_root,
    refresh_attachments,
    resolve_attachments_base_dir,
    resolve_attachments_dir_rel,
    sanitize_attachment_name,
    sanitize_note_stem,
    wrap_with_frontmatter,
)


def test_sanitize_note_stem_strips_obsidian_link_chars() -> None:
    assert sanitize_note_stem("[PROJ-1] Hello | World #tag^v", "fallback") == "PROJ-1 Hello World tagv"


def test_sanitize_note_stem_collapses_whitespace() -> None:
    assert sanitize_note_stem("  multiple   spaces  ", "fb") == "multiple spaces"


def test_sanitize_note_stem_falls_back_when_empty() -> None:
    assert sanitize_note_stem("[]#^|", "page-123") == "page-123"
    assert sanitize_note_stem("   ", "page-123") == "page-123"


def test_sanitize_note_stem_strips_fs_unsafe_chars() -> None:
    assert sanitize_note_stem('a/b\\c:d*e?f"g<h>i', "fb") == "abcdefghi"


def test_sanitize_attachment_name_keeps_dots() -> None:
    assert sanitize_attachment_name("foo bar.png") == "foo bar.png"


def test_sanitize_attachment_name_falls_back_on_empty() -> None:
    assert sanitize_attachment_name("///") == "attachment"


def test_yaml_escape_plain_url_unquoted() -> None:
    assert _yaml_escape("https://example.atlassian.net/wiki/spaces/X/pages/123/Title") == \
        "https://example.atlassian.net/wiki/spaces/X/pages/123/Title"


def test_yaml_escape_plain_title_unquoted() -> None:
    assert _yaml_escape("Hello World") == "Hello World"


def test_yaml_escape_japanese_unquoted() -> None:
    assert _yaml_escape("マスキング方針案") == "マスキング方針案"


def test_yaml_escape_bracket_start_quoted() -> None:
    assert _yaml_escape("[PROJ-1] Summary") == '"[PROJ-1] Summary"'


def test_yaml_escape_colon_space_quoted() -> None:
    assert _yaml_escape("Hello: World") == '"Hello: World"'


def test_yaml_escape_empty_string() -> None:
    assert _yaml_escape("") == '""'


def test_yaml_escape_escapes_inner_quotes() -> None:
    assert _yaml_escape('She said: "hi"') == '"She said: \\"hi\\""'


def test_wrap_with_frontmatter_shape() -> None:
    result = wrap_with_frontmatter(
        body="# Title\n\nbody text\n",
        source_type="confluence",
        url="https://x.atlassian.net/wiki/spaces/X/pages/1/T",
        title="My Title",
    )
    assert result.startswith("---\n")
    assert "confluence_url: https://x.atlassian.net/wiki/spaces/X/pages/1/T\n" in result
    assert "confluence_title: My Title\n" in result
    assert "\n---\n\n# Title" in result


def test_wrap_with_frontmatter_jira() -> None:
    result = wrap_with_frontmatter(
        body="# [PROJ-1] Bug\n",
        source_type="jira",
        url="https://x.atlassian.net/browse/PROJ-1",
        title="[PROJ-1] Bug",
    )
    assert 'jira_title: "[PROJ-1] Bug"' in result
    assert "jira_url: https://x.atlassian.net/browse/PROJ-1" in result


def test_build_attachment_refs_prefixes_page_id() -> None:
    refs = build_attachment_refs(
        page_id="123",
        attachments=[
            {"title": "image one.png", "fileId": "uuid-A", "pageId": "123"},
            {"title": "diagram.svg", "fileId": "uuid-B", "pageId": "123"},
        ],
        attachments_dir_rel=Path("assets"),
    )
    assert refs["image one.png"].target_name == "123-image one.png"
    assert refs["image one.png"].target_rel_path == "assets/123-image one.png"
    assert refs["diagram.svg"].file_id == "uuid-B"
    assert refs["diagram.svg"].page_id == "123"


def test_build_attachment_refs_skips_invalid() -> None:
    refs = build_attachment_refs(
        page_id="123",
        attachments=[
            {"title": "", "fileId": "uuid"},
            {"title": "ok.png", "fileId": ""},
            {"title": "good.png", "fileId": "uuid-good"},
        ],
        attachments_dir_rel=Path("assets"),
    )
    assert list(refs.keys()) == ["good.png"]


def test_build_attachment_refs_falls_back_to_outer_page_id() -> None:
    refs = build_attachment_refs(
        page_id="parent",
        attachments=[{"title": "x.png", "fileId": "uuid-x"}],
        attachments_dir_rel=Path("assets"),
    )
    assert refs["x.png"].page_id == "parent"


def test_refresh_attachments_writes_and_cleans(tmp_path: Path) -> None:
    client = MagicMock()
    client.download_attachment.side_effect = lambda file_id, page_id: f"data-for-{file_id}".encode()

    attachments_dir = tmp_path / "assets"
    attachments_dir.mkdir()
    # Pre-existing stale attachment for this page_id should be deleted
    (attachments_dir / "999-old.png").write_bytes(b"stale")
    # Pre-existing attachment for a *different* page_id should be preserved
    (attachments_dir / "888-other.png").write_bytes(b"other")

    refs = [
        AttachmentRef(
            source_name="new.png",
            target_name="999-new.png",
            target_rel_path="assets/999-new.png",
            file_id="uuid-new",
            page_id="999",
        ),
    ]
    count = refresh_attachments(client, "999", refs, attachments_dir)

    assert count == 1
    assert (attachments_dir / "999-new.png").read_bytes() == b"data-for-uuid-new"
    assert not (attachments_dir / "999-old.png").exists()
    assert (attachments_dir / "888-other.png").exists()
    client.download_attachment.assert_called_once_with(file_id="uuid-new", page_id="999")


def test_resolve_attachments_dir_rel_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from ctxd import auth

    auth._reset_cache_for_tests()
    monkeypatch.delenv("ATTACHMENTS_DIR", raising=False)
    monkeypatch.setattr(auth, "CONFIG_PATH", Path("/nonexistent/ctxd/config"))
    assert resolve_attachments_dir_rel() == Path("assets")


def test_resolve_attachments_dir_rel_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from ctxd import auth

    auth._reset_cache_for_tests()
    monkeypatch.setenv("ATTACHMENTS_DIR", "custom-assets")
    assert resolve_attachments_dir_rel() == Path("custom-assets")


def test_find_vault_root_returns_dir_with_dot_obsidian(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    nested = vault / "folder" / "sub"
    nested.mkdir(parents=True)
    assert find_vault_root(nested) == vault.absolute()


def test_find_vault_root_returns_none_when_not_in_vault(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    # Make sure none of tmp_path's parents have a real .obsidian/ — guarded by absolute path
    # If a parent of tmp_path happens to be a vault, this test would falsely pass; skip if so
    if find_vault_root(plain) is not None:
        pytest.skip("tmp_path lives inside a real Obsidian vault on this machine")
    assert find_vault_root(plain) is None


def test_resolve_attachments_base_dir_uses_vault_root(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    note = vault / "folder" / "sub" / "note.md"
    note.parent.mkdir(parents=True)
    assert resolve_attachments_base_dir(note) == vault.absolute()


def test_resolve_attachments_base_dir_falls_back_to_note_parent(tmp_path: Path) -> None:
    note = tmp_path / "outside" / "note.md"
    note.parent.mkdir(parents=True)
    if find_vault_root(note.parent) is not None:
        pytest.skip("tmp_path lives inside a real Obsidian vault on this machine")
    assert resolve_attachments_base_dir(note) == note.parent
