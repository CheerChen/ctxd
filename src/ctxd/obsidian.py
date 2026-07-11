"""Obsidian-mode helpers for ctxd."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


OBSIDIAN_LINK_CHARS = "[]#^|"


def sanitize_note_stem(title: str, fallback: str) -> str:
    stem = title
    for char in OBSIDIAN_LINK_CHARS:
        stem = stem.replace(char, "")
    stem = re.sub(r'[<>:"/\\|?*]', "", stem)
    stem = re.sub(r"[\x00-\x1f]", "", stem)
    stem = re.sub(r"\s+", " ", stem).strip().strip(".")
    return stem or fallback


def sanitize_attachment_name(name: str) -> str:
    sanitized = re.sub(r'[<>:"|?*\\/]', "", name)
    sanitized = re.sub(r"[\x00-\x1f]", "", sanitized)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized or "attachment"


def _yaml_escape(value: str) -> str:
    if not value:
        return '""'
    first = value[0]
    needs_quote = (
        first in "-?:,[]{}#&*!|>%@`\"' "
        or value.endswith(" ")
        or value.endswith(":")
        or "\n" in value
        or "\r" in value
        or ": " in value
        or " #" in value
    )
    if needs_quote:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def wrap_with_frontmatter(body: str, source_type: str, url: str, title: str) -> str:
    fm = (
        "---\n"
        f"{source_type}_url: {_yaml_escape(url)}\n"
        f"{source_type}_title: {_yaml_escape(title)}\n"
        "---\n\n"
    )
    return fm + body


@dataclass(frozen=True)
class AttachmentRef:
    source_name: str
    target_name: str
    target_rel_path: str
    file_id: str
    page_id: str


def build_attachment_refs(
    page_id: str,
    attachments: list[dict[str, Any]],
    attachments_dir_rel: Path,
) -> dict[str, AttachmentRef]:
    refs: dict[str, AttachmentRef] = {}
    for attachment in attachments:
        source_name = str(attachment.get("title", "")).strip()
        file_id = str(attachment.get("fileId", "")).strip()
        if not source_name or not file_id:
            continue
        attachment_page_id = str(attachment.get("pageId", "")).strip() or page_id
        target_name = f"{page_id}-{sanitize_attachment_name(source_name)}"
        target_rel_path = (attachments_dir_rel / target_name).as_posix()
        refs[source_name] = AttachmentRef(
            source_name=source_name,
            target_name=target_name,
            target_rel_path=target_rel_path,
            file_id=file_id,
            page_id=attachment_page_id,
        )
    return refs


def refresh_attachments(
    client: Any,
    page_id: str,
    desired_refs: list[AttachmentRef],
    attachments_dir_abs: Path,
    max_bytes: int | None = None,
    run_budget=None,
) -> int:
    attachments_dir_abs.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"ctxd-obsidian-{page_id}-"))

    try:
        from ctxd.download_limits import DEFAULT_MAX_FILE_BYTES, DownloadLimitExceeded
        if max_bytes is None:
            max_bytes = DEFAULT_MAX_FILE_BYTES
        staged: list[tuple[Path, Path]] = []
        for ref in desired_refs:
            tmp_path = tmp_dir / ref.target_name
            content = client.download_attachment(
                file_id=ref.file_id, page_id=ref.page_id,
                max_bytes=max_bytes,
            )
            if run_budget is not None:
                run_budget.check_and_reserve(len(content))
            tmp_path.write_bytes(content)
            staged.append((tmp_path, attachments_dir_abs / ref.target_name))

        for tmp_path, target_path in staged:
            os.replace(tmp_path, target_path)

        desired_names = {ref.target_name for ref in desired_refs}
        for existing in attachments_dir_abs.glob(f"{page_id}-*"):
            if existing.name not in desired_names:
                existing.unlink()

        return len(desired_refs)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def resolve_attachments_dir_rel(default: str = "assets") -> Path:
    from ctxd.auth import get_setting

    raw = (get_setting("ATTACHMENTS_DIR") or default).strip() or default
    return Path(raw)


def find_vault_root(start_dir: Path) -> Path | None:
    """Walk up from start_dir looking for a directory containing .obsidian/."""
    current = start_dir.absolute()
    for candidate in (current, *current.parents):
        if (candidate / ".obsidian").is_dir():
            return candidate
    return None


def resolve_attachments_base_dir(output_file: Path) -> Path:
    """Where to anchor a relative ATTACHMENTS_DIR.

    If output_file sits inside an Obsidian vault (any ancestor has .obsidian/),
    use the vault root. Otherwise fall back to the output file's parent.
    """
    parent = output_file.parent
    vault = find_vault_root(parent)
    return vault if vault is not None else parent
