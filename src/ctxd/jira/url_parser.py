"""Jira URL parser."""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Jira Service Management customer portal: /servicedesk/customer/portal/<id>/<KEY>
_PORTAL_PATH_RE = re.compile(r"^servicedesk/customer/portal/\d+/(?P<key>[A-Z][A-Z0-9_]*-\d+)$")


def parse_jira_url(url: str) -> tuple[str, str]:
    """Extract site base URL and issue key from a Jira URL.

    Supports:
      - https://site.atlassian.net/browse/INFRA-10588
      - https://site.atlassian.net/servicedesk/customer/portal/18/SECURITY-1225
    """
    parsed = urlparse(url)
    site = f"{parsed.scheme}://{parsed.netloc}"

    path = parsed.path.strip("/")
    parts = path.split("/")

    if len(parts) >= 2 and parts[0] == "browse":
        return site, parts[1]

    portal = _PORTAL_PATH_RE.match(path)
    if portal:
        return site, portal.group("key")

    raise ValueError(f"Could not extract issue key from URL: {url}")


def is_portal_url(url: str) -> bool:
    """True for a Jira Service Management customer-portal request URL."""
    return bool(_PORTAL_PATH_RE.match(urlparse(url).path.strip("/")))


def project_key(issue_key: str) -> str:
    return issue_key.rsplit("-", 1)[0]
