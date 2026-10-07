"""Confluence non-image attachments: listing and ``--all-attachments`` downloads.

Before this, ``--all-attachments`` did nothing unless ``-i`` was also passed,
and even then it kept only image files — a page whose real content lived in
an attached PDF or spreadsheet exported with no trace of that file.
"""

from __future__ import annotations

import threading
from pathlib import Path

from ctxd.dumpers.confluence import ConfluenceDumper

_BASE = "https://example.atlassian.net"
_PDF = {
    "id": "att1",
    "title": "Report — final.pdf",
    "mediaType": "application/pdf",
    "fileSize": 4242212,
    "pageId": "999",
    "downloadLink": "/rest/api/content/999/child/attachment/att1/download",
}
_PNG = {
    "id": "att2",
    "title": "diagram.png",
    "mediaType": "image/png",
    "fileSize": 2048,
    "pageId": "999",
    "downloadLink": "/rest/api/content/999/child/attachment/att2/download",
}
_PDF_URL = f"{_BASE}/wiki/rest/api/content/999/child/attachment/att1/download"
_HTML_WITH_IMAGE = (
    '<p>body</p><ac:image><ri:attachment ri:filename="diagram.png" /></ac:image>'
)


class _FakeClient:
    base_url = _BASE

    def __init__(self, attachments: list[dict], fail_ids: set[str] | None = None) -> None:
        self._attachments = attachments
        self._fail_ids = fail_ids or set()
        self.downloaded: list[str] = []

    def get_attachments(self, page_id: str) -> list[dict]:
        return self._attachments

    def download_attachment(self, attachment_id: str, page_id: str, max_bytes=None) -> bytes:
        if attachment_id in self._fail_ids:
            raise RuntimeError("boom")
        self.downloaded.append(attachment_id)
        return f"content-of-{attachment_id}".encode()

    def get_inline_comments(self, page_id: str) -> list[dict]:
        return []

    def get_footer_comments(self, page_id: str) -> list[dict]:
        return []

    def get_space_name(self, space_id: str) -> str:
        return space_id

    def get_user_display_name(self, account_id: str) -> str:
        return account_id


def _dumper(tmp_path: Path, client: _FakeClient, **flags) -> ConfluenceDumper:
    dumper = ConfluenceDumper(
        url=f"{_BASE}/wiki/spaces/S/pages/999", output=str(tmp_path / "out"),
        fmt="md", quiet=True, **flags,
    )
    dumper.client = client
    return dumper


def _export(tmp_path: Path, client: _FakeClient, html: str = "<p>body</p>", **flags):
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    page = {"id": "999", "title": "Page", "body": {"storage": {"value": html}}}
    result = _dumper(tmp_path, client, **flags)._export_page(page, out, {}, threading.Lock())
    page_dir = out / "999_Page"
    return result, page_dir, (page_dir / "README.md").read_text(encoding="utf-8")


def test_all_attachments_downloads_pdf_without_images_flag(tmp_path: Path) -> None:
    client = _FakeClient([_PDF])

    _, page_dir, readme = _export(tmp_path, client, all_attachments=True)

    saved = page_dir / "attachments" / "Report — final.pdf"
    assert saved.read_bytes() == b"content-of-att1"
    assert "[Report — final.pdf](<attachments/Report — final.pdf>)" in readme


def test_all_attachments_still_saves_images_under_images_dir(tmp_path: Path) -> None:
    client = _FakeClient([_PDF, _PNG])

    _, page_dir, readme = _export(tmp_path, client, html=_HTML_WITH_IMAGE, all_attachments=True)

    assert (page_dir / "images" / "diagram.png").exists()
    assert not (page_dir / "attachments" / "diagram.png").exists()
    assert "(<images/diagram.png>)" in readme


def test_attachments_listed_without_any_flag(tmp_path: Path) -> None:
    client = _FakeClient([_PDF])

    result, page_dir, readme = _export(tmp_path, client)

    assert client.downloaded == []
    assert not (page_dir / "attachments").exists()
    assert "## Attachments" in readme
    assert f"[Report — final.pdf](<{_PDF_URL}>) — application/pdf, 4.0 MiB" in readme
    assert any("--all-attachments" in note for note in result.notes)


def test_images_flag_alone_does_not_download_pdf(tmp_path: Path) -> None:
    client = _FakeClient([_PDF, _PNG])

    result, page_dir, _ = _export(tmp_path, client, html=_HTML_WITH_IMAGE, include_images=True)

    assert client.downloaded == ["att2"]
    assert not (page_dir / "attachments").exists()
    assert any("1 attachment(s) not downloaded" in note for note in result.notes)


def test_failed_download_keeps_remote_link_and_notes_it(tmp_path: Path) -> None:
    client = _FakeClient([_PDF], fail_ids={"att1"})

    result, _, readme = _export(tmp_path, client, all_attachments=True)

    assert f"(<{_PDF_URL}>)" in readme
    assert any("Report — final.pdf" in note and "boom" in note for note in result.notes)


def test_no_section_when_page_has_no_attachments(tmp_path: Path) -> None:
    _, _, readme = _export(tmp_path, _FakeClient([]))

    assert "## Attachments" not in readme


def test_sanitized_name_collision_gets_id_prefix(tmp_path: Path) -> None:
    a = dict(_PDF, id="attA", title="a:b.pdf")
    b = dict(_PDF, id="attB", title="ab.pdf")
    client = _FakeClient([a, b])

    _, page_dir, _ = _export(tmp_path, client, all_attachments=True)

    names = sorted(p.name for p in (page_dir / "attachments").iterdir())
    assert names == ["ab.pdf", "attB-ab.pdf"] or names == ["ab.pdf", "attA-ab.pdf"]


def test_stdout_transform_lists_attachments_with_remote_urls() -> None:
    client = _FakeClient([_PDF])
    dumper = ConfluenceDumper(url=f"{_BASE}/wiki/spaces/S/pages/999", output=None, fmt="md", quiet=True)
    dumper.client = client
    dumper.summary.notes.clear()
    page = {"id": "999", "title": "Page", "body": {"storage": {"value": "<p>body</p>"}}}

    content = dumper.transform({"page_id": "999", "pages": [page]})

    assert f"[Report — final.pdf](<{_PDF_URL}>)" in content
    assert client.downloaded == []


_VIEW_FILE_HTML = (
    '<ac:structured-macro ac:name="view-file"><ac:parameter ac:name="name">'
    '<ri:attachment ri:filename="Report &mdash; final.pdf" /></ac:parameter></ac:structured-macro>'
)


def test_extracted_filenames_are_html_unescaped() -> None:
    from ctxd.confluence.converter import extract_confluence_images

    assert extract_confluence_images(_VIEW_FILE_HTML) == ["Report — final.pdf"]


def test_embedded_pdf_is_not_reported_as_missing_image(tmp_path: Path) -> None:
    client = _FakeClient([_PDF])

    result, _, _ = _export(tmp_path, client, html=_VIEW_FILE_HTML, all_attachments=True)

    assert client.downloaded == ["att1"]
    assert not any("image(s)" in note for note in result.notes)


def test_entity_escaped_image_resolves_to_downloaded_copy() -> None:
    from ctxd.confluence.converter import html_to_markdown

    html = '<ac:image><ri:attachment ri:filename="a &amp; b.png" /></ac:image>'
    markdown, _, _ = html_to_markdown(html, image_map={"a & b.png": "local/copy.png"})

    assert "local/copy.png" in markdown
