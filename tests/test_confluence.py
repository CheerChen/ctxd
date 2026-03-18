from ctxd.confluence.url_parser import parse_confluence_url


def test_parse_old_confluence_url() -> None:
    site, page_id = parse_confluence_url(
        "https://kinto-dev.atlassian.net/wiki/pages/viewpage.action?pageId=3140419873"
    )
    assert site == "https://kinto-dev.atlassian.net"
    assert page_id == "3140419873"


def test_parse_new_confluence_url() -> None:
    site, page_id = parse_confluence_url(
        "https://kinto-dev.atlassian.net/wiki/spaces/KIDPF/pages/3397648909/title"
    )
    assert site == "https://kinto-dev.atlassian.net"
    assert page_id == "3397648909"
