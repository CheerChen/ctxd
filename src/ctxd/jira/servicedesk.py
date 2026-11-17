"""Jira Service Management fallback.

A customer of a service desk (someone who raised a request through the
portal) has no Browse permission on the project, so the platform API answers
``GET /rest/api/2/issue/{key}`` with 404 — the same body as a key that does
not exist.  The 404 itself cannot tell the two apart, so the decision is made
per project: only when the project is a service desk visible to the caller is
the request read through ``/rest/servicedeskapi/``.  The set of visible
service desks is cached on disk, so a genuine 404 in an ordinary project costs
no extra request.

The service desk API returns a different shape; :func:`to_issue` maps it onto
the platform-API shape the Jira dumper already renders.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

CACHE_TTL_SECONDS = 24 * 3600

NOT_VISIBLE = "(not visible in portal)"


def _cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "ctxd"


def _cache_path(site: str) -> Path:
    host = urlparse(site).netloc or site
    return _cache_dir() / f"jsm-servicedesks-{host}.json"


def service_desk_keys(site: str, fetch: Callable[[], list[str]]) -> set[str]:
    """Project keys of the service desks visible to the caller on *site*.

    Read from a per-site cache younger than :data:`CACHE_TTL_SECONDS`;
    otherwise *fetch* is called and the result cached.  A cache that cannot
    be read or written only costs the next run one request, so I/O errors on
    it are ignored.
    """
    path = _cache_path(site)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - float(data["fetched_at"]) < CACHE_TTL_SECONDS:
            return set(data["keys"])
    except (OSError, ValueError, KeyError, TypeError):
        pass

    keys = fetch()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"fetched_at": time.time(), "keys": sorted(keys)}), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass
    return set(keys)


def _attachment_id(att: dict[str, Any]) -> str:
    """The attachment id, taken from ``_links.jiraRest`` (``…/attachment/<id>``)."""
    links = att.get("_links") or {}
    for link in (links.get("jiraRest"), links.get("content")):
        if link:
            tail = str(link).rstrip("/").rsplit("/", 1)[-1]
            if tail.isdigit():
                return tail
    return ""


def _iso(date: dict[str, Any] | None) -> str:
    return (date or {}).get("iso8601", "")


def to_issue(
    site: str,
    request: dict[str, Any],
    comments: list[dict[str, Any]],
    attachments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Map service desk API responses onto the dumper's raw issue shape.

    Fields the portal does not expose (assignee, priority, labels, …) are set
    to :data:`NOT_VISIBLE` rather than left empty, so the output never claims
    "Unassigned" or "None" for a value it simply could not see.
    """
    key = request.get("issueKey", "")
    request_type = request.get("requestType") or {}
    status = (request.get("currentStatus") or {}).get("status") or NOT_VISIBLE

    summary = ""
    description_html = ""
    description_plain = ""
    custom_fields: list[dict[str, Any]] = []
    for field in request.get("requestFieldValues") or []:
        field_id = field.get("fieldId", "")
        rendered = (field.get("renderedValue") or {}).get("html", "") if isinstance(
            field.get("renderedValue"), dict
        ) else ""
        value = field.get("value")
        if field_id == "summary":
            summary = str(value or "")
        elif field_id == "description":
            description_html = rendered
            description_plain = str(value or "")
        else:
            custom_fields.append(
                {"key": field_id, "name": field.get("label") or field_id, "html": rendered, "value": value}
            )

    portal_id = request_type.get("portalId") or request.get("serviceDeskId") or ""
    url = f"{site}/servicedesk/customer/portal/{portal_id}/{key}" if portal_id else f"{site}/browse/{key}"

    fields = {
        "summary": summary or "Untitled",
        "status": {"name": status},
        "priority": {"name": NOT_VISIBLE},
        "issuetype": {"name": request_type.get("name") or NOT_VISIBLE},
        "assignee": {"displayName": NOT_VISIBLE},
        "reporter": request.get("reporter"),
        "labels": [NOT_VISIBLE],
        "components": [{"name": NOT_VISIBLE}],
        "created": _iso(request.get("createdDate")),
        "updated": NOT_VISIBLE,
        "description": description_plain,
        "attachment": [
            {
                "id": _attachment_id(a),
                "filename": a.get("filename"),
                "mimeType": a.get("mimeType"),
                "size": a.get("size"),
                "content": (a.get("_links") or {}).get("content", ""),
            }
            for a in attachments
        ],
    }

    mapped_comments = [
        {
            "author": c.get("author"),
            "created": _iso(c.get("created")),
            "body": c.get("body", ""),
            "renderedBody": (c.get("renderedBody") or {}).get("html", ""),
        }
        for c in comments
    ]
    return {
        "key": key,
        "url": url,
        "fields": fields,
        # Same place the platform API puts rendered comments, which is where
        # attachment-reference scanning looks.
        "rendered": {"description": description_html, "comment": {"comments": mapped_comments}},
        "request_fields": custom_fields,
        "comments": mapped_comments,
    }
