"""Confluence URL parser."""

from __future__ import annotations

import re
from urllib.parse import urlparse


_SHORT_LINK_RE = re.compile(r"^/wiki/x/(?P<token>[A-Za-z0-9]+)$")


def is_short_link(url: str) -> bool:
    """Return True for Confluence tiny-link URLs of the form ``<site>/wiki/x/<token>``."""
    parsed = urlparse(url)
    return _SHORT_LINK_RE.match(parsed.path) is not None


def parse_short_link(url: str) -> tuple[str, str]:
    """Extract ``(site, token)`` from a Confluence tiny-link URL.

    Raises ``ValueError`` if *url* is not a tiny-link URL.
    """
    parsed = urlparse(url)
    match = _SHORT_LINK_RE.match(parsed.path)
    if not match:
        raise ValueError(f"Not a Confluence short link: {url}")
    site = f"{parsed.scheme}://{parsed.netloc}"
    return site, match.group("token")


def parse_confluence_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    site = f"{parsed.scheme}://{parsed.netloc}"

    if "pageId=" in url:
        page_id = url.split("pageId=")[1].split("&")[0]
        return site, page_id

    path = parsed.path.lstrip("/").rstrip("/")
    parts = path.split("/")

    if (
        len(parts) >= 5
        and parts[0] == "wiki"
        and parts[1] == "spaces"
        and parts[3] == "pages"
        and parts[4].isdigit()
    ):
        return site, parts[4]

    if parts and parts[-1].isdigit():
        return site, parts[-1]

    raise ValueError(f"Could not extract pageId from URL: {url}")
