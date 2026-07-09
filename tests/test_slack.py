import pytest

from ctxd.dumpers.slack import SlackDumper
from ctxd.router import parse_slack_focused_ts


# ---------------------------------------------------------------------------
# _download_files — every attachment gets a stable file-id-suffixed name
# ---------------------------------------------------------------------------

def test_download_files_disambiguates_same_name(monkeypatch, tmp_path) -> None:
    dumper = SlackDumper(
        url="https://example.slack.com/archives/C123/p1735881234123456",
        output=None,
        fmt="md",
        download_files=True,
    )

    # Fake file payloads: four attachments all named "image.png" with distinct IDs.
    files = [
        {"id": "F0AAAAAAA1", "name": "image.png", "url_private_download": "https://slack.com/files/F0AAAAAAA1/dl", "url_private": "https://slack.com/files/F0AAAAAAA1"},
        {"id": "F0AAAAAAA2", "name": "image.png", "url_private_download": "https://slack.com/files/F0AAAAAAA2/dl", "url_private": "https://slack.com/files/F0AAAAAAA2"},
        {"id": "F0AAAAAAA3", "name": "image.png", "url_private_download": "https://slack.com/files/F0AAAAAAA3/dl", "url_private": "https://slack.com/files/F0AAAAAAA3"},
        {"id": "F0AAAAAAA4", "name": "image.png", "url_private_download": "https://slack.com/files/F0AAAAAAA4/dl", "url_private": "https://slack.com/files/F0AAAAAAA4"},
    ]

    def fake_get(url, timeout=60):
        class FakeResp:
            content = url.encode()
            headers = {"content-type": "image/png"}
            def raise_for_status(self): pass
        return FakeResp()

    monkeypatch.setattr(dumper.session, "get", fake_get)

    dumper._download_files(files, tmp_path)

    attachment_dir = tmp_path / "attachments"
    downloaded = sorted(p.name for p in attachment_dir.iterdir())
    # Uniform naming: IMG_{file_id}.{ext} for every attachment.
    assert len(downloaded) == 4
    assert downloaded == [
        "IMG_F0AAAAAAA1.png",
        "IMG_F0AAAAAAA2.png",
        "IMG_F0AAAAAAA3.png",
        "IMG_F0AAAAAAA4.png",
    ]


def test_download_files_always_appends_file_id(monkeypatch, tmp_path) -> None:
    """Uniform naming: IMG_{file_id}.{ext} regardless of original filename."""
    dumper = SlackDumper(
        url="https://example.slack.com/archives/C123/p1735881234123456",
        output=None,
        fmt="md",
        download_files=True,
    )

    files = [
        {"id": "F0AAAAAAA5", "name": "IMG_1862.jpg", "url_private_download": "https://slack.com/files/F0AAAAAAA5/dl"},
    ]

    def fake_get(url, timeout=60):
        class FakeResp:
            content = url.encode()
            headers = {"content-type": "image/jpeg"}
            def raise_for_status(self): pass
        return FakeResp()

    monkeypatch.setattr(dumper.session, "get", fake_get)

    dumper._download_files(files, tmp_path)

    attachment_dir = tmp_path / "attachments"
    downloaded = [p.name for p in attachment_dir.iterdir()]
    assert downloaded == ["IMG_F0AAAAAAA5.jpg"]


def test_download_files_rejects_html_response(monkeypatch, tmp_path) -> None:
    """When the token lacks files:read scope, Slack returns an HTML login
    page with HTTP 200. We must not save that as if it were the file."""
    dumper = SlackDumper(
        url="https://example.slack.com/archives/C123/p1735881234123456",
        output=None,
        fmt="md",
        download_files=True,
    )

    files = [
        {"id": "F0AAAAAAA1", "name": "image.png", "url_private_download": "https://slack.com/files/F0AAAAAAA1/dl"},
    ]

    def fake_get(url, timeout=60):
        class FakeResp:
            content = b"<!DOCTYPE html><html>login page</html>"
            headers = {"content-type": "text/html; charset=utf-8"}
            def raise_for_status(self): pass
        return FakeResp()

    monkeypatch.setattr(dumper.session, "get", fake_get)

    dumper._download_files(files, tmp_path)

    attachment_dir = tmp_path / "attachments"
    # No file should be saved when the response is HTML.
    assert not attachment_dir.exists() or not list(attachment_dir.iterdir())


def test_transform_markdown_includes_channel_and_thread_urls(monkeypatch) -> None:
    monkeypatch.setattr(SlackDumper, "_format_ts", staticmethod(lambda ts: "2025-01-17 18:42:10"))
    dumper = SlackDumper(
        url="https://example.slack.com/archives/C12345678/p1735881234123456",
        output=None,
        fmt="md",
    )

    out = dumper.transform(
        {
            "channel": "C12345678",
            "channel_name": "support-room",
            "thread_ts": "1735881234.123456",
            "messages": [{"ts": "1735881234.123456", "text": "hello"}],
            "participants": [],
        }
    )

    assert "**Channel:** #support-room (C12345678)" in out
    assert "**Channel URL:** https://example.slack.com/archives/C12345678" in out
    assert "**Thread Started:** 2025-01-17 18:42:10" in out
    assert "**Thread URL:** https://example.slack.com/archives/C12345678/p1735881234123456" in out


def test_convert_links_markdown() -> None:
    text = "see <https://example.com|Example>"
    assert SlackDumper._convert_links(text, markdown=True) == "see [Example](https://example.com)"


def test_convert_mrkdwn_to_markdown() -> None:
    text = "*bold* _italic_ ~del~"
    assert SlackDumper._convert_mrkdwn_to_markdown(text) == "**bold** *italic* ~~del~~"


def test_convert_slack_bullet_markers_preserves_hierarchy() -> None:
    text = "• parent\n\t◦ child\n\t\t▪ grandchild"
    assert SlackDumper._convert_mrkdwn_to_markdown(text) == "- parent\n  - child\n    - grandchild"


def test_convert_special_mentions() -> None:
    text = "<!here> <!channel> <!everyone>"
    assert SlackDumper._convert_special_mentions(text) == "@here @channel @everyone"


def test_user_labels_use_name_for_conversation_and_both_names_for_participants(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(SlackDumper, "_format_ts", staticmethod(lambda ts: "timestamp"))
    dumper = SlackDumper(url="https://foo.slack.com/archives/C123/p1735881234123456", output=None, fmt="md")

    def fake_api_call(method: str, params: dict[str, str]) -> dict:
        assert method == "users.info"
        return {
            "ok": True,
            "user": {
                "id": params["user"],
                "name": "sample.user",
                "profile": {
                    "display_name_normalized": "Sample User [out of office]",
                    "real_name_normalized": "Sample User",
                },
            },
        }

    monkeypatch.setattr(dumper, "_api_call", fake_api_call)

    lines = dumper._format_message(
        {"ts": "1735881234.123456", "user": "U123", "text": "cc <@U123>"},
        markdown=True,
        attachment_base_dir=tmp_path,
    )
    participants = dumper._format_participant_lines(["U123"], markdown=True)

    assert lines[0] == "### [@Sample User] timestamp"
    assert "cc @Sample User" in lines
    assert participants == ["- @Sample User [out of office] (Sample User)"]
    assert "[out of office]" not in "\n".join(lines)


def test_conversation_user_name_ignores_display_name() -> None:
    user = {
        "display_name": "Sample User [out of office]",
        "name": "Sample User",
    }

    assert SlackDumper._conversation_user_name(user, "U123") == "Sample User"


# ---------------------------------------------------------------------------
# parse_slack_focused_ts
# ---------------------------------------------------------------------------

def test_focused_ts_returns_reply_ts_when_differs_from_thread_ts() -> None:
    url = "https://example.slack.com/archives/C12345678/p1782880850739909?thread_ts=1782879875.064939&cid=C12345678"
    assert parse_slack_focused_ts(url) == "1782880850.739909"


@pytest.mark.parametrize("url", [
    "https://example.slack.com/archives/C12345678/p1782879875064939?thread_ts=1782879875.064939&cid=C12345678",
    "https://example.slack.com/archives/C12345678/p1782879875064939",
    "https://example.slack.com/client/T123/C12345678/thread/C12345678-1782879875.064939",
])
def test_focused_ts_returns_none(url) -> None:
    assert parse_slack_focused_ts(url) is None


# ---------------------------------------------------------------------------
# SlackDumper focused message rendering
# ---------------------------------------------------------------------------

def test_focused_message_header_and_marker(monkeypatch) -> None:
    monkeypatch.setattr(SlackDumper, "_format_ts", staticmethod(lambda ts: "2026-07-01 13:47:30"))
    dumper = SlackDumper(
        url="https://example.slack.com/archives/C12345678/p1782880850739909?thread_ts=1782879875.064939&cid=C12345678",
        output=None,
        fmt="md",
    )

    def fake_api_call(method: str, params: dict[str, str]) -> dict:
        return {
            "ok": True,
            "user": {
                "id": params["user"],
                "name": "test.user",
                "profile": {"real_name_normalized": "Test User"},
            },
        }

    monkeypatch.setattr(dumper, "_api_call", fake_api_call)

    out = dumper.transform(
        {
            "channel": "C12345678",
            "channel_name": "test-room",
            "thread_ts": "1782879875.064939",
            "messages": [
                {"ts": "1782879875.064939", "text": "root message", "user": "U001"},
                {"ts": "1782880850.739909", "text": "focused reply", "user": "U002"},
            ],
            "participants": ["U001", "U002"],
        }
    )

    # Header should show focused message info
    assert "**Focused Message:**" in out
    assert "@Test User" in out

    # The focused message in conversation should have ▶ marker
    assert "### ▶ [@Test User] 2026-07-01 13:47:30" in out

    # The root message should NOT have the marker
    root_line = [l for l in out.splitlines() if l.startswith("### [") and "▶" not in l]
    assert len(root_line) >= 1


def test_no_focused_message_when_thread_root_url(monkeypatch) -> None:
    monkeypatch.setattr(SlackDumper, "_format_ts", staticmethod(lambda ts: "2026-07-01 13:24:35"))
    dumper = SlackDumper(
        url="https://example.slack.com/archives/C12345678/p1782879875064939",
        output=None,
        fmt="md",
    )

    out = dumper.transform(
        {
            "channel": "C12345678",
            "channel_name": "test-room",
            "thread_ts": "1782879875.064939",
            "messages": [{"ts": "1782879875.064939", "text": "root message", "user": "U001"}],
            "participants": ["U001"],
        }
    )

    # No focused message header when URL points at thread root
    assert "**Focused Message:**" not in out
    # No ▶ marker
    assert "▶" not in out
