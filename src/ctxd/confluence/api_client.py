"""Confluence REST API client."""

from __future__ import annotations

import sys
import threading
from typing import Any, Callable, TypeVar

import requests

from ctxd.concurrency import parallel_map
from ctxd.http_retry import mount_retry
from ctxd.profiling import instrument_session

_T = TypeVar("_T")

# Upper bound the descendants endpoint accepts for ``depth``.
_DESCENDANTS_MAX_DEPTH = 5


def _warn(message: str) -> None:
    """Diagnostic warning — always printed to stderr, never silenced."""
    print(message, file=sys.stderr)


def attachment_download_url(base_url: str, attachment: dict[str, Any]) -> str:
    """Absolute, durable download URL for a Confluence attachment.

    This is the v1 REST download endpoint, which accepts API-token Basic
    auth and 302-redirects to a freshly signed media URL on each request.
    Unlike the media URL itself it embeds no token and does not expire, so
    it is safe to write into an exported artifact.  (The legacy
    ``/wiki/download/attachments/...`` path answers 401 for API tokens.)

    Returns an empty string when the metadata carries no download link.
    """
    link = attachment.get("downloadLink") or ""
    if not link:
        return ""
    return f"{base_url.rstrip('/')}/wiki{link}"


def build_attachment_urls(base_url: str, attachments: list[dict[str, Any]]) -> dict[str, str]:
    """Map ``filename -> download URL`` for the given attachments."""
    urls: dict[str, str] = {}
    for attachment in attachments:
        filename = str(attachment.get("title", "")).strip()
        url = attachment_download_url(base_url, attachment)
        if filename and url:
            urls[filename] = url
    return urls


class ConfluenceClient:
    def __init__(self, base_url: str, email: str, api_token: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = (email, api_token)
        self.session.headers.update({"Accept": "application/json"})
        mount_retry(self.session)
        instrument_session(self.session, "confluence")
        self._user_cache: dict[str, str] = {}
        self._space_cache: dict[str, str] = {}
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
            except Exception as exc:
                _warn(f"⚠ Confluence: failed to resolve user {account_id}: {exc}")
                return account_id

        return self._locked_compute(self._user_cache, account_id, "user", fetch)

    def get_space_name(self, space_id: str) -> str:
        def fetch() -> str:
            try:
                url = f"{self.base_url}/wiki/api/v2/spaces/{space_id}"
                resp = self.session.get(url, timeout=10)
                resp.raise_for_status()
                return resp.json().get("name", space_id)
            except Exception as exc:
                _warn(f"⚠ Confluence: failed to resolve space {space_id}: {exc}")
                return space_id

        return self._locked_compute(self._space_cache, space_id, "space", fetch)

    def get_page(self, page_id: str) -> dict[str, Any]:
        url = f"{self.base_url}/wiki/api/v2/pages/{page_id}?body-format=storage"
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _paginate(
        self, path: str, params: dict[str, Any], missing_ok: bool = False,
    ) -> list[dict[str, Any]]:
        """Every result of a v2 collection, following ``_links.next``.

        ``next`` is a relative path that already carries the cursor
        (``/wiki/api/v2/...?cursor=...``), so it is requested as-is.
        With *missing_ok*, a 400/404 on the first request means the
        collection does not exist and yields ``[]``; an error on a later
        page always raises, so a broken cursor cannot pass for "no more".
        """
        results: list[dict[str, Any]] = []
        url: str | None = f"{self.base_url}{path}"
        query: dict[str, Any] | None = params
        while url:
            resp = self.session.get(url, params=query, timeout=30)
            try:
                resp.raise_for_status()
            except requests.exceptions.HTTPError:
                if missing_ok and query is not None and resp.status_code in (400, 404):
                    return []
                raise
            data = resp.json()
            results.extend(data.get("results", []))
            next_path = data.get("_links", {}).get("next")
            url = f"{self.base_url}{next_path}" if next_path else None
            query = None
        return results

    def get_descendants(self, page_id: str) -> list[dict[str, Any]]:
        """Every descendant page, however deep.

        The endpoint defaults to depth 2 and caps ``depth`` at 5, so pages
        found at the cap are queried again as new roots.  ``depth`` on the
        returned pages is rewritten to be relative to *page_id*.
        """
        pages: list[dict[str, Any]] = []
        frontier: list[tuple[str, int]] = [(page_id, 0)]
        while frontier:
            batches = parallel_map(
                lambda root: self._paginate(
                    f"/wiki/api/v2/pages/{root[0]}/descendants",
                    {"limit": 250, "depth": _DESCENDANTS_MAX_DEPTH},
                ),
                frontier,
            )
            next_frontier: list[tuple[str, int]] = []
            for (_, offset), batch in zip(frontier, batches):
                for page in batch:
                    relative = int(page.get("depth") or 0)
                    page["depth"] = offset + relative
                    pages.append(page)
                    if relative == _DESCENDANTS_MAX_DEPTH and page.get("type", "page") == "page":
                        next_frontier.append((str(page["id"]), page["depth"]))
            frontier = next_frontier
        return pages

    def get_attachments(self, page_id: str) -> list[dict[str, Any]]:
        return self._paginate(
            f"/wiki/api/v2/pages/{page_id}/attachments", {"limit": 100}, missing_ok=True,
        )

    def get_inline_comments(self, page_id: str) -> list[dict[str, Any]]:
        return self._paginate(
            f"/wiki/api/v2/pages/{page_id}/inline-comments",
            {"limit": 100, "body-format": "storage"}, missing_ok=True,
        )

    def get_footer_comments(self, page_id: str) -> list[dict[str, Any]]:
        return self._paginate(
            f"/wiki/api/v2/pages/{page_id}/footer-comments",
            {"limit": 100, "body-format": "storage"}, missing_ok=True,
        )

    def get_comment_children(self, comment_id: str, comment_type: str = "footer") -> list[dict[str, Any]]:
        return self._paginate(
            f"/wiki/api/v2/{comment_type}-comments/{comment_id}/children",
            {"limit": 100, "body-format": "storage"}, missing_ok=True,
        )

    def download_attachment(
        self, attachment_id: str, page_id: str, max_bytes: int | None = None
    ) -> bytes:
        # The legacy /wiki/download/attachments/... endpoint rejects API token
        # Basic auth with 401 (its WWW-Authenticate hint demands OAuth), but
        # the v1 REST download endpoint accepts it and 302-redirects to a
        # freshly signed media URL. requests drops the Authorization header on
        # that cross-host hop, which is exactly what the signed URL wants — so
        # no hand-built media token is needed.
        url = (
            f"{self.base_url}/wiki/rest/api/content/{page_id}"
            f"/child/attachment/{attachment_id}/download"
        )
        resp = self.session.get(url, timeout=60, stream=True, headers={"Accept": "*/*"})
        resp.raise_for_status()
        # Check Content-Length against per-file limit before downloading.
        # max_bytes < 0 or None means unlimited.
        if max_bytes is not None and max_bytes >= 0:
            content_length = int(resp.headers.get("Content-Length", 0))
            if content_length and content_length > max_bytes:
                resp.close()
                from ctxd.download_limits import DownloadLimitExceeded
                raise DownloadLimitExceeded(
                    f"file too large: {content_length} > {max_bytes} bytes"
                )
        # Stream-download with size enforcement.
        chunks: list[bytes] = []
        total = 0
        try:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if max_bytes is not None and max_bytes >= 0 and total > max_bytes:
                    raise DownloadLimitExceeded(
                        f"file too large: streamed {total} > {max_bytes} bytes"
                    )
                chunks.append(chunk)
        finally:
            resp.close()
        return b"".join(chunks)


