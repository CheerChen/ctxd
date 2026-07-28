from __future__ import annotations

from pathlib import Path

import pytest

from ctxd.dumpers.jira import JiraDumper
from ctxd.jira.attachments import (
    parse_attachments,
    referenced_ids,
    rewrite_attachment_links,
    select_attachments,
)

_SITE = "https://example.atlassian.net"
_IMG = {
    "id": "543376",
    "filename": "diagram.png",
    "mimeType": "image/png",
    "size": 134885,
    "content": f"{_SITE}/rest/api/2/attachment/content/543376",
}
_PDF = {
    "id": "99",
    "filename": "report.pdf",
    "mimeType": "application/pdf",
    "size": 2048,
    "content": f"{_SITE}/rest/api/2/attachment/content/99",
}
_DESCRIPTION_HTML = (
    '<p>see</p><img src="https://example.atlassian.net/rest/api/3/attachment/content/543376" '
    'alt="diagram.png" />'
)


def test_parse_attachments() -> None:
    attachments = parse_attachments({"attachment": [_IMG, _PDF]})

    assert [a.id for a in attachments] == ["543376", "99"]
    assert attachments[0].is_image is True
    assert attachments[1].is_image is False


def test_parse_attachments_missing_field() -> None:
    assert parse_attachments({}) == []


@pytest.mark.parametrize("text,expected", [
    (_DESCRIPTION_HTML, {"543376"}),
    ("![x](https://example.atlassian.net/rest/api/2/attachment/content/7)", {"7"}),
    ("/rest/api/3/attachment/content/12345", {"12345"}),
    ('<img src="https://example.atlassian.net/rest/api/3/attachment/thumbnail/8">', {"8"}),
    ("no attachments here", set()),
])
def test_referenced_ids(text: str, expected: set[str]) -> None:
    assert referenced_ids(text) == expected


def test_select_none_without_flags() -> None:
    attachments = parse_attachments({"attachment": [_IMG, _PDF]})

    assert select_attachments(attachments, {"543376"}, False, False) == []


def test_select_include_images_only_referenced_images() -> None:
    attachments = parse_attachments({"attachment": [_IMG, _PDF]})

    selected = select_attachments(attachments, {"543376", "99"}, True, False)

    assert [a.id for a in selected] == ["543376"]


def test_select_include_images_skips_unreferenced() -> None:
    attachments = parse_attachments({"attachment": [_IMG]})

    assert select_attachments(attachments, set(), True, False) == []


def test_select_all_attachments_ignores_references() -> None:
    attachments = parse_attachments({"attachment": [_IMG, _PDF]})

    selected = select_attachments(attachments, set(), False, True)

    assert [a.id for a in selected] == ["543376", "99"]


def test_target_name_prefixes_attachment_id() -> None:
    attachment = parse_attachments({"attachment": [{**_IMG, "filename": "a/b: c.png"}]})[0]

    assert attachment.target_name() == "543376-ab c.png"


def test_rewrite_attachment_links_uses_local_path() -> None:
    content = f"![diagram.png]({_SITE}/rest/api/3/attachment/content/543376)"

    result = rewrite_attachment_links(content, {"543376": "issue_attachments/543376-diagram.png"})

    assert result == "![diagram.png](issue_attachments/543376-diagram.png)"


def test_rewrite_attachment_links_keeps_undownloaded_urls() -> None:
    content = f"![report]({_SITE}/rest/api/3/attachment/content/99)"

    assert rewrite_attachment_links(content, {"543376": "x.png"}) == content


# ---------------------------------------------------------------------------
# Dumper integration
# ---------------------------------------------------------------------------

class _FakeClient:
    def __init__(self, payload: bytes = b"binary", fail: bool = False) -> None:
        self.payload = payload
        self.fail = fail
        self.calls: list[str] = []

    def download_attachment(self, attachment_id, content_url="", max_bytes=None) -> bytes:
        self.calls.append(attachment_id)
        if self.fail:
            raise RuntimeError("boom")
        return self.payload


def _raw() -> dict:
    return {
        "key": "INFRA-1",
        "fields": {
            "summary": "Issue with an image",
            "attachment": [_IMG, _PDF],
        },
        "rendered": {"description": _DESCRIPTION_HTML},
        "names": {},
        "custom_fields": [],
        "comments": [],
    }


def _dumper(tmp_path: Path, **kwargs) -> JiraDumper:
    dumper = JiraDumper(
        url=f"{_SITE}/browse/INFRA-1",
        output=str(tmp_path / "issue.md"),
        fmt="md",
        quiet=True,
        **kwargs,
    )
    dumper.client = _FakeClient()
    return dumper


def test_transform_without_flags_notes_skipped_attachments(tmp_path: Path) -> None:
    dumper = _dumper(tmp_path)

    content = dumper.transform(_raw())

    assert not (tmp_path / "issue_attachments").exists()
    assert "2 attachment(s) not downloaded" in " ".join(dumper.summary.notes)
    # The remote URL is preserved so the reader can still fetch it.
    assert f"{_SITE}/rest/api/3/attachment/content/543376" in content


def test_transform_include_images_downloads_and_rewrites(tmp_path: Path) -> None:
    dumper = _dumper(tmp_path, include_images=True)

    content = dumper.transform(_raw())

    saved = tmp_path / "issue_attachments" / "543376-diagram.png"
    assert saved.read_bytes() == b"binary"
    assert "issue_attachments/543376-diagram.png" in content
    # The unreferenced PDF is not downloaded by -i.
    assert dumper.client.calls == ["543376"]


def test_transform_all_attachments_downloads_everything(tmp_path: Path) -> None:
    dumper = _dumper(tmp_path, all_attachments=True)

    dumper.transform(_raw())

    assert sorted(p.name for p in (tmp_path / "issue_attachments").iterdir()) == [
        "543376-diagram.png",
        "99-report.pdf",
    ]


def test_attachments_section_lists_every_attachment(tmp_path: Path) -> None:
    content = _dumper(tmp_path, all_attachments=True).transform(_raw())

    assert "## Attachments" in content
    assert "[report.pdf](issue_attachments/99-report.pdf) — application/pdf, 2.0 KiB" in content


def test_attachments_section_in_text_format(tmp_path: Path) -> None:
    dumper = _dumper(tmp_path, all_attachments=True)
    dumper.fmt = "text"

    content = dumper.transform(_raw())

    assert "--- ATTACHMENTS ---" in content
    assert "diagram.png (image/png, 131.7 KiB): issue_attachments/543376-diagram.png" in content


def test_download_failure_is_loud_and_counted(tmp_path: Path) -> None:
    dumper = _dumper(tmp_path, all_attachments=True)
    dumper.client = _FakeClient(fail=True)

    content = dumper.transform(_raw())

    assert dumper.summary.failed == 2
    assert any("attachment download failed" in note for note in dumper.summary.notes)
    # Links fall back to the remote URL when the download failed.
    assert f"{_SITE}/rest/api/2/attachment/content/99" in content


def test_stdout_output_skips_download(tmp_path: Path) -> None:
    dumper = JiraDumper(
        url=f"{_SITE}/browse/INFRA-1", output=None, fmt="md", quiet=True, all_attachments=True,
    )
    dumper.client = _FakeClient()

    dumper.transform(_raw())

    assert dumper.client.calls == []
    assert any("no output path" in note for note in dumper.summary.notes)
