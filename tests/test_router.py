from ctxd.router import Source, detect, parse_github_pr_url, parse_slack_thread_url


def test_detect_github_pr() -> None:
    assert detect("https://github.com/o/r/pull/123") is Source.GITHUB_PR


def test_detect_slack() -> None:
    assert detect("https://foo.slack.com/archives/C123/p1735881234123456") is Source.SLACK_THREAD


def test_detect_confluence() -> None:
    assert detect("https://foo.atlassian.net/wiki/spaces/ABC/pages/1234/title") is Source.CONFLUENCE


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
