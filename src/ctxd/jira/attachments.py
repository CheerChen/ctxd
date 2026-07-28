"""Jira attachment selection and link rewriting.

Jira exposes every attachment of an issue in ``fields.attachment``, and the
rendered description / comment HTML references them by attachment id:

    <img src="https://site.atlassian.net/rest/api/3/attachment/content/543376">

So no extra API call is needed to discover attachments — only to download
them.  The helpers here are pure so the selection and rewriting rules stay
testable without network access.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Attachment URL forms seen in rendered Jira HTML / Markdown.
# The API version varies (2 or 3); a thumbnail carries the same id as the
# full-size file, so both resolve to the same downloaded copy.
_ATTACHMENT_URL_RE = re.compile(
    r"(?:https?://[^\s)\"']+)?"
    r"/rest/api/\d+/attachment/(?:content|thumbnail)/(?P<id>\d+)"
)

_IMAGE_MIME_PREFIX = "image/"


@dataclass(frozen=True)
class JiraAttachment:
    """One entry of ``fields.attachment``, normalised."""

    id: str
    filename: str
    mime_type: str
    size: int
    content_url: str

    @property
    def is_image(self) -> bool:
        return self.mime_type.startswith(_IMAGE_MIME_PREFIX)

    def target_name(self) -> str:
        """Local filename: attachment id prefix keeps it unique even when an
        issue has several attachments sharing the same filename."""
        return f"{self.id}-{sanitize_attachment_name(self.filename)}"


def sanitize_attachment_name(name: str) -> str:
    sanitized = re.sub(r'[<>:"|?*\\/]', "", name)
    sanitized = re.sub(r"[\x00-\x1f]", "", sanitized)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized or "attachment"


def parse_attachments(fields: dict) -> list[JiraAttachment]:
    """Normalise ``fields.attachment`` into :class:`JiraAttachment` objects."""
    result: list[JiraAttachment] = []
    for item in fields.get("attachment") or []:
        att_id = str(item.get("id", "")).strip()
        if not att_id:
            continue
        result.append(
            JiraAttachment(
                id=att_id,
                filename=str(item.get("filename") or f"attachment-{att_id}"),
                mime_type=str(item.get("mimeType") or ""),
                size=int(item.get("size") or 0),
                content_url=str(item.get("content") or ""),
            )
        )
    return result


def referenced_ids(*html_or_markdown: str) -> set[str]:
    """Attachment ids referenced from the given rendered HTML / Markdown."""
    found: set[str] = set()
    for text in html_or_markdown:
        if not text:
            continue
        for match in _ATTACHMENT_URL_RE.finditer(text):
            found.add(match.group("id"))
    return found


def select_attachments(
    attachments: list[JiraAttachment],
    referenced: set[str],
    include_images: bool,
    all_attachments: bool,
) -> list[JiraAttachment]:
    """Decide what to download.

    - ``all_attachments``: everything attached to the issue.
    - ``include_images``: only images referenced from the issue body — the
      same rule Confluence ``-i`` follows.
    """
    if all_attachments:
        return list(attachments)
    if include_images:
        return [a for a in attachments if a.is_image and a.id in referenced]
    return []


def rewrite_attachment_links(content: str, local_paths: dict[str, str]) -> str:
    """Point attachment URLs at their downloaded local copies.

    *local_paths* maps attachment id → path relative to the output file.
    Ids that were not downloaded keep their original remote URL.
    """
    if not local_paths:
        return content

    def _replace(match: re.Match[str]) -> str:
        return local_paths.get(match.group("id"), match.group(0))

    return _ATTACHMENT_URL_RE.sub(_replace, content)


def format_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KiB"
    return f"{num_bytes / (1024 * 1024):.1f} MiB"
