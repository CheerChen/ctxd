"""Confluence REST API client."""

from __future__ import annotations

from typing import Any

import requests


class ConfluenceClient:
    def __init__(self, base_url: str, email: str, api_token: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = (email, api_token)
        self.session.headers.update({"Accept": "application/json"})

    def get_page(self, page_id: str) -> dict[str, Any]:
        url = f"{self.base_url}/wiki/api/v2/pages/{page_id}?body-format=storage"
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_descendants(self, page_id: str) -> list[dict[str, Any]]:
        all_pages: list[dict[str, Any]] = []
        cursor: str | None = None

        while True:
            params = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            url = f"{self.base_url}/wiki/api/v2/pages/{page_id}/descendants"
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            all_pages.extend(data.get("results", []))
            cursor = data.get("_links", {}).get("next")
            if not cursor:
                break
        return all_pages

    def get_attachments(self, page_id: str) -> list[dict[str, Any]]:
        all_attachments: list[dict[str, Any]] = []
        cursor: str | None = None

        while True:
            params = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            url = f"{self.base_url}/wiki/api/v2/pages/{page_id}/attachments"
            try:
                resp = self.session.get(url, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except requests.exceptions.HTTPError as exc:
                if exc.response is not None and exc.response.status_code in (400, 404):
                    break
                raise

            all_attachments.extend(data.get("results", []))
            cursor = data.get("_links", {}).get("next")
            if not cursor:
                break

        return all_attachments

    def download_attachment(self, download_link: str) -> bytes:
        if download_link.startswith("/"):
            url = f"{self.base_url}/wiki{download_link}"
        else:
            url = f"{self.base_url}/wiki/{download_link}"
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        return resp.content
