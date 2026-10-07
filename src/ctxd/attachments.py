"""Source-independent attachment helpers shared by the Jira and Confluence dumpers."""

from __future__ import annotations

import re


def sanitize_attachment_name(name: str) -> str:
    sanitized = re.sub(r'[<>:"|?*\\/]', "", name)
    sanitized = re.sub(r"[\x00-\x1f]", "", sanitized)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized or "attachment"


def format_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KiB"
    return f"{num_bytes / (1024 * 1024):.1f} MiB"
