"""Jira REST API client."""

from __future__ import annotations

from typing import Any

import requests

from ctxd.http_retry import mount_retry
from ctxd.profiling import instrument_session


class JiraClient:
    def __init__(self, base_url: str, email: str, api_token: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = (email, api_token)
        self.session.headers.update({"Accept": "application/json"})
        mount_retry(self.session)
        instrument_session(self.session, "jira")

    def get_issue(self, issue_key: str) -> dict[str, Any]:
        url = f"{self.base_url}/rest/api/2/issue/{issue_key}"
        params = {"expand": "renderedFields,names"}
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def download_attachment(
        self, attachment_id: str, content_url: str = "", max_bytes: int | None = None
    ) -> bytes:
        """Download one attachment's binary content.

        Unlike Confluence, the Jira attachment endpoint accepts API-token
        Basic auth directly.  It redirects to a pre-signed media URL on a
        different host; requests drops the Authorization header on that hop,
        which is what the signed URL expects.
        """
        url = content_url or f"{self.base_url}/rest/api/3/attachment/content/{attachment_id}"
        resp = self.session.get(url, timeout=60, stream=True, headers={"Accept": "*/*"})
        resp.raise_for_status()

        from ctxd.download_limits import DownloadLimitExceeded

        unlimited = max_bytes is None or max_bytes < 0
        if not unlimited:
            content_length = int(resp.headers.get("Content-Length", 0))
            if content_length and content_length > max_bytes:
                resp.close()
                raise DownloadLimitExceeded(
                    f"file too large: {content_length} > {max_bytes} bytes"
                )

        chunks: list[bytes] = []
        total = 0
        try:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if not unlimited and total > max_bytes:
                    raise DownloadLimitExceeded(
                        f"file too large: streamed {total} > {max_bytes} bytes"
                    )
                chunks.append(chunk)
        finally:
            resp.close()
        return b"".join(chunks)

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

    # -- Jira Service Management (customer portal) API ----------------------
    # A portal customer has no Browse permission on the project, so the
    # platform API above answers 404; /rest/servicedeskapi/ serves the same
    # request as the portal shows it (public comments only).

    def _servicedesk_pages(self, path: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        start = 0
        while True:
            query = {**(params or {}), "start": str(start), "limit": "100"}
            resp = self.session.get(f"{self.base_url}{path}", params=query, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            page = data.get("values", [])
            values.extend(page)
            if data.get("isLastPage", True) or not page:
                return values
            start += len(page)

    def get_service_desk_project_keys(self) -> list[str]:
        desks = self._servicedesk_pages("/rest/servicedeskapi/servicedesk")
        return [d["projectKey"] for d in desks if d.get("projectKey")]

    def get_request(self, issue_key: str) -> dict[str, Any]:
        url = f"{self.base_url}/rest/servicedeskapi/request/{issue_key}"
        params = {"expand": "renderedFieldValues,requestType,status,participant"}
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_request_comments(self, issue_key: str) -> list[dict[str, Any]]:
        return self._servicedesk_pages(
            f"/rest/servicedeskapi/request/{issue_key}/comment", {"expand": "renderedBody"}
        )

    def get_request_attachments(self, issue_key: str) -> list[dict[str, Any]]:
        return self._servicedesk_pages(f"/rest/servicedeskapi/request/{issue_key}/attachment")
