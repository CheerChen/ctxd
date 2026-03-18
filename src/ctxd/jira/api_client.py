"""Jira REST API client."""

from __future__ import annotations

from typing import Any

import requests


class JiraClient:
    def __init__(self, base_url: str, email: str, api_token: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = (email, api_token)
        self.session.headers.update({"Accept": "application/json"})

    def get_issue(self, issue_key: str) -> dict[str, Any]:
        url = f"{self.base_url}/rest/api/2/issue/{issue_key}"
        params = {"expand": "renderedFields,names"}
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_comments(self, issue_key: str) -> list[dict[str, Any]]:
        all_comments: list[dict[str, Any]] = []
        start_at = 0

        while True:
            url = f"{self.base_url}/rest/api/2/issue/{issue_key}/comment"
            params = {"startAt": str(start_at), "maxResults": "100", "expand": "renderedBody"}
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            comments = data.get("comments", [])
            all_comments.extend(comments)
            total = data.get("total", 0)
            start_at += len(comments)
            if start_at >= total or not comments:
                break

        return all_comments
