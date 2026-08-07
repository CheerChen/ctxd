"""GitHub REST API client.

Replaces the previous ``gh`` CLI shell-outs so GitHub auth works the same way
as every other source: a token resolved from the environment or
``~/.config/ctxd/config``, with no dependency on an external binary or on
whichever account ``gh`` happens to have active in the current directory.
"""

from __future__ import annotations

import threading
from typing import Any

import requests

from ctxd.http_retry import mount_retry
from ctxd.profiling import instrument_session

API_ROOT = "https://api.github.com"

# Sent on every request so a future GitHub API change cannot silently alter
# response shapes underneath us.
API_VERSION = "2022-11-28"


class GitHubAPIError(RuntimeError):
    """A GitHub API call returned a non-2xx status."""


_ACCESS_HINT = (
    "\n   GITHUB_TOKEN may not have access to this repository."
    " Verify it is a classic PAT with the 'repo' scope, and that it"
    " is SSO-authorized for the owning organization."
)


class GitHubClient:
    # A token that cannot see the repo fails all five parallel PR reads the
    # same way. Print the remediation hint once instead of five times; each
    # individual failure is still reported with its own status and path.
    _hint_lock = threading.Lock()
    _hint_shown = False

    @classmethod
    def _access_hint(cls) -> str:
        with cls._hint_lock:
            if cls._hint_shown:
                return ""
            cls._hint_shown = True
            return _ACCESS_HINT

    @classmethod
    def _reset_hint_for_tests(cls) -> None:
        cls._hint_shown = False

    def __init__(self, token: str, base_url: str = API_ROOT):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
        })
        mount_retry(self.session)
        instrument_session(self.session, "github")

    # ------------------------------------------------------------------
    # Error reporting
    # ------------------------------------------------------------------

    @classmethod
    def _check(cls, resp: requests.Response, what: str) -> None:
        """Raise ``GitHubAPIError`` with an actionable message on non-2xx.

        The old ``gh`` path surfaced raw CLI stderr, which for a private repo
        the token cannot see reads as "repository does not exist" — a dead end
        for anyone (human or agent) trying to fix it. Name the likely cause.
        """
        if resp.ok:
            return

        detail = ""
        try:
            payload = resp.json()
            if isinstance(payload, dict):
                detail = str(payload.get("message", "") or "")
        except ValueError:
            detail = (resp.text or "").strip()[:200]

        msg = f"GitHub API {resp.status_code} on {what}: {detail or resp.reason}"

        if resp.status_code == 403 and resp.headers.get("x-ratelimit-remaining") == "0":
            reset = resp.headers.get("x-ratelimit-reset", "")
            msg += f"\n   Rate limit exhausted (resets at epoch {reset})."
        elif resp.status_code in (401, 403, 404):
            msg += cls._access_hint()

        raise GitHubAPIError(msg)

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    def get_pull(self, owner: str, repo: str, number: str) -> dict[str, Any]:
        """Fetch PR metadata (title, body, state, ...)."""
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{number}"
        resp = self.session.get(url, timeout=30)
        self._check(resp, f"pulls/{number}")
        return resp.json()

    def paginate(self, path: str) -> list[dict[str, Any]]:
        """Follow ``Link: rel="next"`` and return every item as one flat list.

        Replaces ``gh api --paginate --slurp``.
        """
        items: list[dict[str, Any]] = []
        url: str | None = f"{self.base_url}{path}"
        params: dict[str, str] | None = {"per_page": "100"}

        while url:
            resp = self.session.get(url, params=params, timeout=30)
            self._check(resp, path)
            page = resp.json()
            if isinstance(page, list):
                items.extend(item for item in page if isinstance(item, dict))
            elif isinstance(page, dict):
                items.append(page)
            # The next link already carries per_page and page params.
            url = resp.links.get("next", {}).get("url")
            params = None

        return items

    def get_diff(self, owner: str, repo: str, number: str) -> str:
        """Fetch the unified diff for a PR.

        Same endpoint as ``get_pull`` with a diff media type — this is exactly
        what ``gh pr diff`` did, including GitHub's own size caps.
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{number}"
        resp = self.session.get(
            url,
            timeout=60,
            headers={"Accept": "application/vnd.github.v3.diff"},
        )
        self._check(resp, f"pulls/{number}.diff")
        return resp.text
