import pytest

from ctxd.router import Source, detect, parse_github_pr_url, parse_slack_thread_url


@pytest.mark.parametrize("url,expected", [
    ("https://github.com/o/r/pull/123", Source.GITHUB_PR),
    ("https://foo.slack.com/archives/C123/p1735881234123456", Source.SLACK_THREAD),
    ("https://foo.atlassian.net/wiki/spaces/ABC/pages/1234/title", Source.CONFLUENCE),
    ("https://foo.atlassian.net/browse/PROJ-1", Source.JIRA),
])
def test_detect(url, expected) -> None:
    assert detect(url) is expected


def test_parse_github_pr_url() -> None:
    assert parse_github_pr_url("https://github.com/owner/repo/pull/42") == ("owner", "repo", "42")


def test_parse_slack_archives_url() -> None:
    channel, ts = parse_slack_thread_url("https://foo.slack.com/archives/C12345678/p1735881234123456")
    assert channel == "C12345678"
    assert ts == "1735881234.123456"


def test_parse_slack_client_url() -> None:
    channel, ts = parse_slack_thread_url(
        "https://foo.slack.com/client/T123/C12345678/thread/C12345678-1735881234.123456"
    )
    assert channel == "C12345678"
    assert ts == "1735881234.123456"
