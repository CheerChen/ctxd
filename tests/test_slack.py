from ctxd.dumpers.slack import SlackDumper


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
