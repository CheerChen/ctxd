"""Confluence URL parser."""

from __future__ import annotations

from urllib.parse import urlparse


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
