from ctxd.dumpers.slack import SlackDumper


def test_convert_links_markdown() -> None:
    text = "see <https://example.com|Example>"
    assert SlackDumper._convert_links(text, markdown=True) == "see [Example](https://example.com)"


def test_convert_mrkdwn_to_markdown() -> None:
    text = "*bold* _italic_ ~del~"
    assert SlackDumper._convert_mrkdwn_to_markdown(text) == "**bold** *italic* ~~del~~"


def test_convert_special_mentions() -> None:
    text = "<!here> <!channel> <!everyone>"
    assert SlackDumper._convert_special_mentions(text) == "@here @channel @everyone"
