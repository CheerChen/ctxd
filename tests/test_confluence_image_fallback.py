"""Images that were not downloaded must still be reachable.

Before this, any run that did not pass ``-i`` rendered embedded images as
``images/<filename>`` — a relative path to a directory that only exists for
a directory export with ``-i``. Every other mode produced a dead link with
no URL to fall back on.
"""

from __future__ import annotations

import pytest

from ctxd.confluence.api_client import attachment_download_url, build_attachment_urls
from ctxd.confluence.converter import html_to_markdown, resolve_image_src
from ctxd.dumpers.confluence import ConfluenceDumper

_BASE = "https://example.atlassian.net"
_ATTACHMENT = {
    "id": "att123",
    "title": "diagram.png",
    "downloadLink": "/rest/api/content/999/child/attachment/att123/download",
}
_DOWNLOAD_URL = f"{_BASE}/wiki/rest/api/content/999/child/attachment/att123/download"
_HTML = '<ac:image ac:alt="d"><ri:attachment ri:filename="diagram.png" /></ac:image>'


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------

def test_attachment_download_url_makes_relative_link_absolute() -> None:
    assert attachment_download_url(_BASE, _ATTACHMENT) == _DOWNLOAD_URL


def test_attachment_download_url_accepts_trailing_slash_base() -> None:
    assert attachment_download_url(f"{_BASE}/", _ATTACHMENT) == _DOWNLOAD_URL


def test_attachment_download_url_empty_without_link() -> None:
    assert attachment_download_url(_BASE, {"title": "x.png"}) == ""


def test_build_attachment_urls_skips_entries_without_link() -> None:
    urls = build_attachment_urls(_BASE, [_ATTACHMENT, {"title": "no-link.png"}])

    assert urls == {"diagram.png": _DOWNLOAD_URL}


# ---------------------------------------------------------------------------
# Resolution order
# ---------------------------------------------------------------------------

def test_local_copy_wins_over_remote_url() -> None:
    src = resolve_image_src("diagram.png", {"diagram.png": "images/diagram.png"},
                            {"diagram.png": _DOWNLOAD_URL})

    assert src == "images/diagram.png"


def test_remote_url_used_when_not_downloaded() -> None:
    assert resolve_image_src("diagram.png", {}, {"diagram.png": _DOWNLOAD_URL}) == _DOWNLOAD_URL


def test_unknown_attachment_keeps_relative_path() -> None:
    """drawio / plantuml output may not exist as an attachment at all."""
    assert resolve_image_src("diagram.png", {}, {}) == "images/diagram.png"


@pytest.mark.parametrize("html", [
    _HTML,
    '<ac:structured-macro ac:name="drawio">'
    '<ac:parameter ac:name="diagramName">diagram</ac:parameter></ac:structured-macro>',
    '<ac:structured-macro ac:name="plantuml">'
    '<ac:parameter ac:name="filename">diagram.png</ac:parameter></ac:structured-macro>',
])
def test_html_to_markdown_uses_fallback_url(html: str) -> None:
    markdown, _, _ = html_to_markdown(html, image_map={}, fallback_urls={"diagram.png": _DOWNLOAD_URL})

    assert _DOWNLOAD_URL in markdown
    assert "images/diagram.png" not in markdown


# ---------------------------------------------------------------------------
# Dumper wiring
# ---------------------------------------------------------------------------

class _FakeClient:
    base_url = _BASE

    def __init__(self, attachments=None) -> None:
        self._attachments = attachments if attachments is not None else [_ATTACHMENT]
        self.calls = 0

    def get_attachments(self, page_id: str):
        self.calls += 1
        return self._attachments


def _dumper(client: _FakeClient) -> ConfluenceDumper:
    dumper = ConfluenceDumper(url=f"{_BASE}/wiki/spaces/S/pages/999", output=None, fmt="md", quiet=True)
    dumper.client = client
    return dumper


def test_no_api_call_for_pages_without_images() -> None:
    client = _FakeClient()
    dumper = _dumper(client)

    urls = dumper._image_fallback_urls("999", "<p>text only</p>", image_map={})

    assert urls == {}
    assert client.calls == 0


def test_fetches_attachments_once_for_pages_with_images() -> None:
    client = _FakeClient()
    notes: list[str] = []

    urls = _dumper(client)._image_fallback_urls("999", _HTML, image_map={}, notes_out=notes)

    assert urls == {"diagram.png": _DOWNLOAD_URL}
    assert client.calls == 1
    assert any("not downloaded (use -i)" in note for note in notes)


def test_reuses_supplied_attachments_without_refetching() -> None:
    client = _FakeClient()

    _dumper(client)._image_fallback_urls("999", _HTML, image_map={}, attachments=[_ATTACHMENT])

    assert client.calls == 0


def test_no_note_when_every_image_was_downloaded() -> None:
    notes: list[str] = []

    _dumper(_FakeClient())._image_fallback_urls(
        "999", _HTML, image_map={"diagram.png": "images/diagram.png"}, notes_out=notes,
    )

    assert notes == []


def test_note_names_images_with_no_attachment_url() -> None:
    notes: list[str] = []

    _dumper(_FakeClient(attachments=[]))._image_fallback_urls(
        "999", _HTML, image_map={}, notes_out=notes,
    )

    assert any("no attachment URL: diagram.png" in note for note in notes)
