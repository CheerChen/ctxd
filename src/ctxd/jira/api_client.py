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
