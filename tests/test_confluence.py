from unittest.mock import MagicMock, patch

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


def test_get_space_name_resolves_and_caches() -> None:
    from ctxd.confluence.api_client import ConfluenceClient

    client = ConfluenceClient(
        base_url="https://kinto-dev.atlassian.net", email="x@x", api_token="t"
    )
    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "98765", "name": "DBRE Handbook"}
    mock_response.raise_for_status.return_value = None
    with patch.object(client.session, "get", return_value=mock_response) as mock_get:
        assert client.get_space_name("98765") == "DBRE Handbook"
        # Second call should hit cache, not re-query
        assert client.get_space_name("98765") == "DBRE Handbook"
        assert mock_get.call_count == 1
        called_url = mock_get.call_args.args[0]
        assert called_url == "https://kinto-dev.atlassian.net/wiki/api/v2/spaces/98765"


def test_get_space_name_degrades_to_id_on_exception() -> None:
    from ctxd.confluence.api_client import ConfluenceClient

    client = ConfluenceClient(
        base_url="https://kinto-dev.atlassian.net", email="x@x", api_token="t"
    )
    with patch.object(client.session, "get", side_effect=RuntimeError("boom")):
        assert client.get_space_name("98765") == "98765"


def _make_page(
    *,
    page_id: str = "123",
    title: str = "Example",
    space_id: str = "98765",
    author_id: str = "acc-author",
    created_at: str = "2026-03-02T04:15:22.123Z",
    version_created_at: str = "2026-04-16T07:23:11.456Z",
    webui: str = "/spaces/DBRE/pages/123/Example",
    body_html: str = "<p>hello</p>",
) -> dict:
    page: dict = {
        "id": page_id,
        "title": title,
        "spaceId": space_id,
        "authorId": author_id,
        "createdAt": created_at,
        "version": {"createdAt": version_created_at},
        "_links": {"webui": webui},
        "body": {"storage": {"value": body_html}},
    }
    return page


def _make_dumper():
    from ctxd.confluence.api_client import ConfluenceClient
    from ctxd.dumpers.confluence import ConfluenceDumper

    dumper = ConfluenceDumper(
        url="https://kinto-dev.atlassian.net/wiki/spaces/DBRE/pages/123/Example",
        output=None,
        fmt="md",
        quiet=True,
    )
    client = ConfluenceClient(
        base_url="https://kinto-dev.atlassian.net", email="x@x", api_token="t"
    )
    client._user_cache["acc-author"] = "佐藤 誠"
    client._space_cache["98765"] = "DBRE Handbook"
    dumper.client = client
    return dumper, client


def test_build_metadata_block_happy_path() -> None:
    dumper, _ = _make_dumper()
    block = dumper._build_metadata_block(_make_page())
    assert "## Metadata" in block
    assert "| **Space** | DBRE Handbook |" in block
    assert "| **Author** | 佐藤 誠 |" in block
    assert "| **Created** | 2026-03-02 |" in block
    assert "| **Last Modified** | 2026-04-16 |" in block
    assert (
        "| **URL** | https://kinto-dev.atlassian.net/wiki/spaces/DBRE/pages/123/Example |"
        in block
    )
    assert block.endswith("\n")


def test_build_metadata_block_degrades_when_author_unresolved() -> None:
    dumper, client = _make_dumper()
    # Remove cached display name and make the session call raise -> fallback to accountId
    client._user_cache.clear()
    page = _make_page(author_id="ghost-account")
    with patch.object(client.session, "get", side_effect=RuntimeError("boom")):
        block = dumper._build_metadata_block(page)
    assert "| **Author** | ghost-account |" in block


def test_build_metadata_block_degrades_when_space_unresolved() -> None:
    dumper, client = _make_dumper()
    client._space_cache.clear()
    page = _make_page(space_id="orphan-space")
    with patch.object(client.session, "get", side_effect=RuntimeError("boom")):
        block = dumper._build_metadata_block(page)
    assert "| **Space** | orphan-space |" in block


def test_build_metadata_block_degrades_when_fields_missing() -> None:
    dumper, _ = _make_dumper()
    page = {"id": "123", "title": "Example"}  # no authorId / spaceId / createdAt / ...
    block = dumper._build_metadata_block(page)
    assert "| **Space** | Unknown |" in block
    assert "| **Author** | Unknown |" in block
    assert "| **Created** | Unknown |" in block
    assert "| **Last Modified** | Unknown |" in block
    assert "| **URL** | Unknown |" in block


def test_build_metadata_block_handles_malformed_date() -> None:
    dumper, _ = _make_dumper()
    page = _make_page(
        created_at="not-a-date", version_created_at="2026-04-16something"
    )
    block = dumper._build_metadata_block(page)
    # Malformed → pass through the first 10 chars as a best-effort YYYY-MM-DD
    assert "| **Created** | not-a-date |" in block
    assert "| **Last Modified** | 2026-04-16 |" in block


def test_transform_prepends_metadata_block_and_offsets_marker_map() -> None:
    dumper, _ = _make_dumper()
    page = _make_page(body_html="<p>body content</p>")
    raw = {"page_id": "123", "pages": [page]}
    # Stub comment fetchers so transform() runs without network
    dumper.client.get_inline_comments = lambda pid: []  # type: ignore[assignment]
    dumper.client.get_footer_comments = lambda pid: []  # type: ignore[assignment]
    result = dumper.transform(raw)
    assert result.startswith("# Example\n\n## Metadata\n")
    assert "| **Space** | DBRE Handbook |" in result
    # Body content must appear AFTER the metadata table
    space_idx = result.index("| **Space**")
    body_idx = result.index("body content")
    assert body_idx > space_idx
