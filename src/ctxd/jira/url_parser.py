"""Jira URL parser."""

from __future__ import annotations

from urllib.parse import urlparse


def parse_jira_url(url: str) -> tuple[str, str]:
    """Extract site base URL and issue key from a Jira URL.

    Supports:
      - https://site.atlassian.net/browse/INFRA-10588
    """
    parsed = urlparse(url)
    site = f"{parsed.scheme}://{parsed.netloc}"

    path = parsed.path.strip("/")
    parts = path.split("/")

    if len(parts) >= 2 and parts[0] == "browse":
        return site, parts[1]

    raise ValueError(f"Could not extract issue key from URL: {url}")
