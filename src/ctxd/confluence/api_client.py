"""Confluence REST API client."""

from __future__ import annotations

import base64
import json
import threading
from typing import Any, Callable, TypeVar

import requests

from ctxd.http_retry import mount_retry
from ctxd.profiling import instrument_session

_T = TypeVar("_T")


class ConfluenceClient:
    def __init__(self, base_url: str, email: str, api_token: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = (email, api_token)
        self.session.headers.update({"Accept": "application/json"})
        mount_retry(self.session)
        instrument_session(self.session, "confluence")
        # Media downloads use URL-embedded tokens, not Basic auth.
        self._media_session = requests.Session()
        mount_retry(self._media_session)
        instrument_session(self._media_session, "confluence_media")
        self._user_cache: dict[str, str] = {}
        self._space_cache: dict[str, str] = {}
        self._media_token_cache: dict[str, tuple[str, str, str]] = {}
        # Per-cache key-level locks so concurrent fetches for the SAME key
        # collapse to one HTTP call, while different keys remain parallel.
        self._cache_meta_lock = threading.Lock()
        self._key_locks: dict[tuple[str, str], threading.Lock] = {}

    def _locked_compute(
        self,
        cache: dict[str, _T],
        key: str,
        cache_name: str,
        compute: Callable[[], _T],
    ) -> _T:
        if key in cache:
            return cache[key]
        with self._cache_meta_lock:
            if key in cache:
                return cache[key]
            lock = self._key_locks.setdefault((cache_name, key), threading.Lock())
        with lock:
            if key in cache:
                return cache[key]
            value = compute()
            cache[key] = value
        return value

    def get_user_display_name(self, account_id: str) -> str:
        def fetch() -> str:
            try:
                url = f"{self.base_url}/wiki/rest/api/user?accountId={account_id}"
                resp = self.session.get(url, timeout=10)
                resp.raise_for_status()
                return resp.json().get("displayName", account_id)
            except Exception:
                return account_id

        return self._locked_compute(self._user_cache, account_id, "user", fetch)

    def get_space_name(self, space_id: str) -> str:
        def fetch() -> str:
            try:
                url = f"{self.base_url}/wiki/api/v2/spaces/{space_id}"
                resp = self.session.get(url, timeout=10)
                resp.raise_for_status()
                return resp.json().get("name", space_id)
            except Exception:
                return space_id

        return self._locked_compute(self._space_cache, space_id, "space", fetch)

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

    def get_inline_comments(self, page_id: str) -> list[dict[str, Any]]:
        all_comments: list[dict[str, Any]] = []
        cursor: str | None = None

        while True:
            params: dict[str, Any] = {"limit": 100, "body-format": "storage"}
            if cursor:
                params["cursor"] = cursor
            url = f"{self.base_url}/wiki/api/v2/pages/{page_id}/inline-comments"
            try:
                resp = self.session.get(url, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except requests.exceptions.HTTPError as exc:
                if exc.response is not None and exc.response.status_code in (400, 404):
                    break
                raise

            all_comments.extend(data.get("results", []))
            cursor = data.get("_links", {}).get("next")
            if not cursor:
                break

        return all_comments

    def get_footer_comments(self, page_id: str) -> list[dict[str, Any]]:
        all_comments: list[dict[str, Any]] = []
        cursor: str | None = None

        while True:
            params: dict[str, Any] = {"limit": 100, "body-format": "storage"}
            if cursor:
                params["cursor"] = cursor
            url = f"{self.base_url}/wiki/api/v2/pages/{page_id}/footer-comments"
            try:
                resp = self.session.get(url, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except requests.exceptions.HTTPError as exc:
                if exc.response is not None and exc.response.status_code in (400, 404):
                    break
                raise

            all_comments.extend(data.get("results", []))
            cursor = data.get("_links", {}).get("next")
            if not cursor:
                break

        return all_comments

    def get_comment_children(self, comment_id: str, comment_type: str = "footer") -> list[dict[str, Any]]:
        all_children: list[dict[str, Any]] = []
        cursor: str | None = None

        while True:
            params: dict[str, Any] = {"limit": 100, "body-format": "storage"}
            if cursor:
                params["cursor"] = cursor
            url = f"{self.base_url}/wiki/api/v2/{comment_type}-comments/{comment_id}/children"
            try:
                resp = self.session.get(url, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except requests.exceptions.HTTPError as exc:
                if exc.response is not None and exc.response.status_code in (400, 404):
                    break
                raise

            all_children.extend(data.get("results", []))
            cursor = data.get("_links", {}).get("next")
            if not cursor:
                break

        return all_children

    def download_attachment(self, file_id: str, page_id: str) -> bytes:
        # The legacy /wiki/download/attachments/... endpoint rejects API token
        # Basic auth with 401 (its WWW-Authenticate hint demands OAuth). The
        # working path is the Atlassian Media Service, which accepts a per-page
        # JWT mediaToken issued by the v1 REST API.
        token, client_id, collection_id = self._get_media_token(page_id)
        url = (
            f"https://api.media.atlassian.com/file/{file_id}/binary"
            f"?token={token}&client={client_id}&collection={collection_id}"
        )
        resp = self._media_session.get(url, timeout=60)
        resp.raise_for_status()
        return resp.content

    def _get_media_token(self, page_id: str) -> tuple[str, str, str]:
        def fetch() -> tuple[str, str, str]:
            url = f"{self.base_url}/wiki/rest/api/content/{page_id}?expand=body.view.mediaToken"
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            mt = (data.get("body", {}).get("view", {}) or {}).get("mediaToken") or {}
            token = mt.get("token")
            collection_ids = mt.get("collectionIds") or []
            if not token or not collection_ids:
                raise RuntimeError(f"No mediaToken returned for page {page_id}")

            payload_b64 = token.split(".")[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)
            client_id = json.loads(base64.urlsafe_b64decode(payload_b64))["iss"]
            return (token, client_id, collection_ids[0])

        return self._locked_compute(self._media_token_cache, page_id, "media_token", fetch)
