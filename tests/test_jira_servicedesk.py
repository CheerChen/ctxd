"""Jira Service Management fallback: routing, the 404 decision, the cache, mapping."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

import pytest
import requests

from ctxd.jira.attachments import referenced_ids, rewrite_attachment_links
from ctxd.jira.servicedesk import NOT_VISIBLE, service_desk_keys, to_issue
from ctxd.jira.url_parser import is_portal_url, parse_jira_url
from ctxd.router import Source, detect

SITE = "https://example.atlassian.net"
PORTAL_URL = f"{SITE}/servicedesk/customer/portal/18/SECURITY-1225"
BROWSE_URL = f"{SITE}/browse/SECURITY-1225"


@pytest.fixture(autouse=True)
def _cache_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    return tmp_path


def test_portal_url_routes_and_parses() -> None:
    assert detect(PORTAL_URL) is Source.JIRA
    assert parse_jira_url(PORTAL_URL) == (SITE, "SECURITY-1225")
    assert is_portal_url(PORTAL_URL)
    assert not is_portal_url(BROWSE_URL)


def test_portal_landing_page_is_not_an_issue() -> None:
    with pytest.raises(ValueError):
        parse_jira_url(f"{SITE}/servicedesk/customer/portal/18")


def _http_404() -> requests.HTTPError:
    resp = requests.Response()
    resp.status_code = 404
    return requests.HTTPError("404", response=resp)


def _request_payload() -> dict:
    return {
        "issueKey": "SECURITY-1225",
        "serviceDeskId": "18",
        "createdDate": {"iso8601": "2026-03-27T12:35:44+0900"},
        "reporter": {"displayName": "Reporter"},
        "currentStatus": {"status": "Resolved"},
        "requestType": {"name": "Security question", "portalId": "18"},
        "requestFieldValues": [
            {"fieldId": "summary", "label": "Subject", "value": "Masking audit"},
            {
                "fieldId": "description",
                "label": "Details",
                "value": "raw *wiki*",
                "renderedValue": {"html": "<p>rendered <strong>body</strong></p>"},
            },
            {"fieldId": "customfield_1", "label": "Team", "value": "DBRE"},
        ],
    }


def _dumper(url: str, client: MagicMock):
    from ctxd.dumpers.jira import JiraDumper

    dumper = JiraDumper(url=url, output=None, fmt="md")
    dumper.client = client
    return dumper


def _client(service_desks: list[str]) -> MagicMock:
    client = MagicMock()
    client.base_url = SITE
    client.get_issue.side_effect = _http_404()
    client.get_service_desk_project_keys.return_value = service_desks
    client.get_request.return_value = _request_payload()
    client.get_request_comments.return_value = [
        {
            "author": {"displayName": "Agent"},
            "created": {"iso8601": "2026-03-28T10:00:00+0900"},
            "body": "ok",
            "renderedBody": {"html": "<p>ok</p>"},
        }
    ]
    client.get_request_attachments.return_value = []
    return client


def test_404_outside_service_desks_stays_404_without_jsm_call() -> None:
    client = _client(service_desks=["OTHER"])
    with pytest.raises(requests.HTTPError):
        _dumper(BROWSE_URL, client).fetch()
    client.get_request.assert_not_called()


def test_404_in_visible_service_desk_reads_customer_api() -> None:
    client = _client(service_desks=["SECURITY"])
    raw = _dumper(BROWSE_URL, client).fetch()
    client.get_request.assert_called_once_with("SECURITY-1225")
    assert raw["fields"]["summary"] == "Masking audit"
    assert raw["custom_fields"] == [
        {"key": "customfield_1", "name": "Team", "content": "DBRE", "type": "request"}
    ]


def test_portal_url_skips_service_desk_lookup() -> None:
    client = _client(service_desks=[])
    _dumper(PORTAL_URL, client).fetch()
    client.get_service_desk_project_keys.assert_not_called()
    client.get_request.assert_called_once()


def test_non_404_error_is_not_retried_through_jsm() -> None:
    client = _client(service_desks=["SECURITY"])
    resp = requests.Response()
    resp.status_code = 401
    client.get_issue.side_effect = requests.HTTPError("401", response=resp)
    with pytest.raises(requests.HTTPError):
        _dumper(PORTAL_URL, client).fetch()
    client.get_request.assert_not_called()


def test_rendered_output_marks_portal_view() -> None:
    client = _client(service_desks=["SECURITY"])
    dumper = _dumper(BROWSE_URL, client)
    out = dumper.transform(dumper.fetch())
    assert "# [SECURITY-1225] Masking audit" in out
    assert f"| **Assignee** | {NOT_VISIBLE} |" in out
    assert f"| **URL** | {PORTAL_URL} |" in out
    assert "rendered **body**" in out
    assert "## Team" in out
    assert "> ok" in out
    assert any("service desk customer API" in n for n in dumper.summary.notes)


def test_service_desk_keys_cached_within_ttl() -> None:
    fetch = MagicMock(return_value=["SECURITY"])
    assert service_desk_keys(SITE, fetch) == {"SECURITY"}
    assert service_desk_keys(SITE, fetch) == {"SECURITY"}
    fetch.assert_called_once()


def test_service_desk_keys_refetched_after_ttl(_cache_home) -> None:
    path = _cache_home / "ctxd" / "jsm-servicedesks-example.atlassian.net.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"fetched_at": time.time() - 2 * 86400, "keys": ["OLD"]}))
    fetch = MagicMock(return_value=["NEW"])
    assert service_desk_keys(SITE, fetch) == {"NEW"}
    assert json.loads(path.read_text())["keys"] == ["NEW"]


def test_to_issue_maps_attachments() -> None:
    raw = to_issue(
        SITE,
        _request_payload(),
        [],
        [
            {
                "filename": "shot.png",
                "mimeType": "image/png",
                "size": 10,
                "_links": {
                    "jiraRest": f"{SITE}/rest/api/2/attachment/546997",
                    "content": f"{SITE}/rest/servicedeskapi/request/574519/attachment/546997",
                },
            }
        ],
    )
    att = raw["fields"]["attachment"][0]
    assert att["id"] == "546997"
    assert att["content"].endswith("/rest/servicedeskapi/request/574519/attachment/546997")


def test_portal_attachment_urls_are_recognised() -> None:
    html = (
        f'<img src="{SITE}/servicedesk/customer/request/574519/attachment/546997">'
        f'<img src="{SITE}/rest/servicedeskapi/request/574519/attachment/546998/thumbnail">'
    )
    assert referenced_ids(html) == {"546997", "546998"}
    out = rewrite_attachment_links(html, {"546997": "a/546997-shot.png", "546998": "a/546998-x.png"})
    assert 'src="a/546997-shot.png"' in out
    assert 'src="a/546998-x.png"' in out
