"""Confluence v2 collections must come back complete.

Two truncations stacked here. Every paginated call passed ``_links.next`` —
a full relative path — back as the ``cursor`` parameter, which the API
answers with 400, so only the first page of any collection was ever read
(and the attachment / comment loops swallowed that 400 as "no more").
And ``get_descendants`` sent no ``depth``, which defaults to 2, so ``-r``
stopped at grandchildren. A 51-page tree exported 18 pages, silently.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
import requests

from ctxd.confluence.api_client import ConfluenceClient

_BASE = "https://example.atlassian.net"


class _Resp:
    def __init__(self, payload: dict | None, status: int = 200) -> None:
        self._payload = payload or {}
        self.status_code = status

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code}", response=self)


class _FakeSession:
    """Serves ``routes[(path, cursor)]``; records every request."""

    def __init__(self, routes: dict[tuple[str, str | None], _Resp]) -> None:
        self.routes = routes
        self.requests: list[tuple[str, dict]] = []

    def get(self, url: str, params=None, timeout=None, **_):
        parsed = urlparse(url)
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        query.update({k: str(v) for k, v in (params or {}).items()})
        self.requests.append((parsed.path, query))
        key = (parsed.path, query.get("cursor"))
        if key not in self.routes:
            return _Resp({"message": "bad cursor"}, status=400)
        return self.routes[key]


def _client(routes) -> tuple[ConfluenceClient, _FakeSession]:
    client = ConfluenceClient(_BASE, "e", "t")
    session = _FakeSession(routes)
    client.session = session
    return client, session


def _page(pid: str, depth: int) -> dict:
    return {"id": pid, "type": "page", "depth": depth, "title": pid}


def _next(path: str, cursor: str) -> dict:
    return {"next": f"{path}?limit=250&cursor={cursor}"}


_ATT = "/wiki/api/v2/pages/1/attachments"
_DESC = "/wiki/api/v2/pages/{}/descendants"


def test_follows_next_link_across_pages() -> None:
    client, _ = _client({
        (_ATT, None): _Resp({"results": [{"id": "a"}], "_links": _next(_ATT, "c2")}),
        (_ATT, "c2"): _Resp({"results": [{"id": "b"}], "_links": _next(_ATT, "c3")}),
        (_ATT, "c3"): _Resp({"results": [{"id": "c"}]}),
    })

    assert [a["id"] for a in client.get_attachments("1")] == ["a", "b", "c"]


def test_missing_collection_on_first_request_is_empty() -> None:
    client, _ = _client({(_ATT, None): _Resp(None, status=404)})

    assert client.get_attachments("1") == []


def test_error_after_first_page_raises_instead_of_truncating() -> None:
    client, _ = _client({
        (_ATT, None): _Resp({"results": [{"id": "a"}], "_links": _next(_ATT, "gone")}),
    })

    with pytest.raises(requests.exceptions.HTTPError):
        client.get_attachments("1")


def test_descendants_requests_max_depth() -> None:
    client, session = _client({(_DESC.format("1"), None): _Resp({"results": [_page("2", 1)]})})

    client.get_descendants("1")

    assert session.requests[0][1]["depth"] == "5"


def test_descendants_continue_below_the_depth_cap() -> None:
    client, _ = _client({
        (_DESC.format("1"), None): _Resp({"results": [_page("2", 1), _page("5", 5)]}),
        (_DESC.format("5"), None): _Resp({"results": [_page("6", 1), _page("7", 5)]}),
        (_DESC.format("7"), None): _Resp({"results": [_page("8", 2)]}),
    })

    pages = client.get_descendants("1")

    assert {p["id"]: p["depth"] for p in pages} == {"2": 1, "5": 5, "6": 6, "7": 10, "8": 12}


def test_descendants_paginate_within_each_query() -> None:
    path = _DESC.format("1")
    client, _ = _client({
        (path, None): _Resp({"results": [_page("2", 1)], "_links": _next(path, "c2")}),
        (path, "c2"): _Resp({"results": [_page("3", 2)]}),
    })

    assert [p["id"] for p in client.get_descendants("1")] == ["2", "3"]


def test_recursive_fetch_reports_tree_size() -> None:
    from unittest.mock import MagicMock

    from ctxd.dumpers.confluence import ConfluenceDumper
    from ctxd.summary import Summary

    dumper = ConfluenceDumper(url=f"{_BASE}/wiki/spaces/S/pages/1", output=None, fmt="md", recursive=True)
    dumper.summary = Summary(source="confluence")
    dumper.client = MagicMock()
    dumper.client.get_page.return_value = {"id": "1"}
    dumper.client.get_descendants.return_value = [_page("2", 1), _page("3", 7)]

    raw = dumper.fetch()

    assert len(raw["pages"]) == 3
    assert "page tree: 2 descendant page(s), max depth 7" in dumper.summary.notes
