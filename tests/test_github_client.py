"""Tests for the GitHub REST client that replaced the ``gh`` CLI shell-outs.

The error-message tests are the point of the migration: the old ``gh`` path
surfaced "Could not resolve to a Repository", which reads as "does not exist"
when the real cause is a token that cannot see it.
"""

from __future__ import annotations

import json

import pytest
import requests

from ctxd.github.api_client import API_ROOT, GitHubAPIError, GitHubClient


def _response(
    status: int = 200,
    json_body=None,
    text: str = "",
    headers: dict[str, str] | None = None,
) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    resp.reason = "Test Reason"
    resp.url = f"{API_ROOT}/x"
    resp.headers.update(headers or {})
    if json_body is not None:
        resp._content = json.dumps(json_body).encode()
        resp.headers.setdefault("Content-Type", "application/json")
    else:
        resp._content = text.encode()
    return resp


def _client() -> GitHubClient:
    return GitHubClient("test-token")


@pytest.fixture(autouse=True)
def _reset_hint():
    """The access hint is once-per-process, so tests must start clean."""
    GitHubClient._reset_hint_for_tests()
    yield
    GitHubClient._reset_hint_for_tests()


# ---------------------------------------------------------------------------
# Actionable error messages
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", [401, 403, 404])
def test_auth_shaped_errors_name_the_token(status: int) -> None:
    """401/403/404 must point at GITHUB_TOKEN, not just echo GitHub's text."""
    resp = _response(status, json_body={"message": "Not Found"})

    with pytest.raises(GitHubAPIError) as exc:
        GitHubClient._check(resp, "pulls/1")

    message = str(exc.value)
    assert f"GitHub API {status}" in message
    assert "pulls/1" in message
    assert "Not Found" in message
    assert "GITHUB_TOKEN" in message
    assert "repo" in message
    assert "SSO" in message


def test_exhausted_rate_limit_is_not_reported_as_a_token_problem() -> None:
    """A 403 from rate limiting needs different advice than a scope problem."""
    resp = _response(
        403,
        json_body={"message": "API rate limit exceeded"},
        headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1700000000"},
    )

    with pytest.raises(GitHubAPIError) as exc:
        GitHubClient._check(resp, "pulls/1")

    message = str(exc.value)
    assert "Rate limit exhausted" in message
    assert "1700000000" in message
    assert "GITHUB_TOKEN" not in message


def test_access_hint_is_emitted_only_once() -> None:
    """All five parallel PR reads fail alike; the advice belongs on one of them."""
    messages = []
    for _ in range(3):
        with pytest.raises(GitHubAPIError) as exc:
            GitHubClient._check(_response(404, json_body={"message": "Not Found"}), "p")
        messages.append(str(exc.value))

    assert sum("GITHUB_TOKEN" in m for m in messages) == 1
    # Every failure still reports itself, hint or not.
    assert all("GitHub API 404" in m for m in messages)


def test_non_json_error_body_falls_back_to_text() -> None:
    resp = _response(500, text="<html>upstream boom</html>")

    with pytest.raises(GitHubAPIError, match="upstream boom"):
        GitHubClient._check(resp, "pulls/1")


def test_success_does_not_raise() -> None:
    assert GitHubClient._check(_response(200, json_body={}), "pulls/1") is None


# ---------------------------------------------------------------------------
# Pagination (replaces `gh api --paginate --slurp`)
# ---------------------------------------------------------------------------

def test_paginate_follows_link_header_and_flattens(monkeypatch) -> None:
    client = _client()
    page2 = f"{API_ROOT}/repos/o/r/pulls/1/comments?page=2"
    calls: list[tuple[str, dict | None]] = []

    def fake_get(url, params=None, timeout=None, headers=None):
        calls.append((url, params))
        if len(calls) == 1:
            return _response(
                200,
                json_body=[{"id": 1}, {"id": 2}],
                headers={"Link": f'<{page2}>; rel="next"'},
            )
        return _response(200, json_body=[{"id": 3}])

    monkeypatch.setattr(client.session, "get", fake_get)

    items = client.paginate("/repos/o/r/pulls/1/comments")

    assert [i["id"] for i in items] == [1, 2, 3]
    # First request asks for the max page size; the next link already carries
    # its own paging params, so they must not be re-sent.
    assert calls[0][1] == {"per_page": "100"}
    assert calls[1] == (page2, None)


def test_paginate_raises_on_error_status(monkeypatch) -> None:
    client = _client()
    monkeypatch.setattr(
        client.session,
        "get",
        lambda *a, **kw: _response(404, json_body={"message": "Not Found"}),
    )

    with pytest.raises(GitHubAPIError):
        client.paginate("/repos/o/r/pulls/1/comments")


def test_paginate_ignores_non_dict_entries(monkeypatch) -> None:
    client = _client()
    monkeypatch.setattr(
        client.session,
        "get",
        lambda *a, **kw: _response(200, json_body=[{"id": 1}, "junk", None]),
    )

    assert client.paginate("/x") == [{"id": 1}]


# ---------------------------------------------------------------------------
# Diff (replaces `gh pr diff`)
# ---------------------------------------------------------------------------

def test_get_diff_requests_the_diff_media_type(monkeypatch) -> None:
    client = _client()
    seen: dict = {}

    def fake_get(url, timeout=None, headers=None, params=None):
        seen["url"] = url
        seen["headers"] = headers
        return _response(200, text="diff --git a/x b/x\n")

    monkeypatch.setattr(client.session, "get", fake_get)

    out = client.get_diff("o", "r", "7")

    assert out == "diff --git a/x b/x\n"
    assert seen["url"] == f"{API_ROOT}/repos/o/r/pulls/7"
    assert seen["headers"]["Accept"] == "application/vnd.github.v3.diff"


# ---------------------------------------------------------------------------
# Session setup
# ---------------------------------------------------------------------------

def test_session_carries_auth_and_api_version() -> None:
    headers = _client().session.headers
    assert headers["Authorization"] == "Bearer test-token"
    assert headers["Accept"] == "application/vnd.github+json"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"


def test_get_pull_returns_payload(monkeypatch) -> None:
    client = _client()
    monkeypatch.setattr(
        client.session,
        "get",
        lambda *a, **kw: _response(200, json_body={"title": "T", "body": "B"}),
    )

    assert client.get_pull("o", "r", "1") == {"title": "T", "body": "B"}
