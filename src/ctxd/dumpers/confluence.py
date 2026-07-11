"""Confluence page dumper."""

from __future__ import annotations

import os
import re
import sys
import threading
from datetime import datetime
from pathlib import Path

from ctxd.auth import ensure_confluence_auth
from ctxd.concurrency import parallel_map
from ctxd.confluence.api_client import ConfluenceClient
from ctxd.confluence.converter import comments_to_markdown, extract_confluence_images, html_to_markdown
from ctxd.confluence.url_parser import is_short_link, parse_confluence_url, parse_short_link
from ctxd.dumpers.base import BaseDumper
from ctxd.profiling import timed
from ctxd.summary import ExportResult, PageStatus, Summary


class ConfluenceDumper(BaseDumper):
    def __init__(
        self,
        url: str,
        output: str | None,
        fmt: str,
        quiet: bool = False,
        verbose: bool = False,
        recursive: bool = False,
        include_images: bool = False,
        all_attachments: bool = False,
        debug: bool = False,
        obsidian_mode: bool = False,
        obsidian_auto_output: bool = False,
    ):
        super().__init__(url=url, output=output, fmt=fmt, quiet=quiet, verbose=verbose)
        self.recursive = recursive
        self.include_images = include_images
        self.all_attachments = all_attachments
        self.debug = debug
        self.obsidian_mode = obsidian_mode
        self.obsidian_auto_output = obsidian_auto_output
        self.client: ConfluenceClient | None = None

    def validate_auth(self) -> None:
        base_url, email, token = ensure_confluence_auth()
        self.client = ConfluenceClient(base_url=base_url, email=email, api_token=token)

    def render(self) -> str:
        self.summary = Summary(source="confluence")
        self.validate_auth()
        self._resolve_short_link()
        with timed("stage.fetch"):
            raw = self.fetch()
        self.summary.resources_fetched = 1
        with timed("stage.transform"):
            content = self.transform(raw)
        self.summary.resources_rendered = 1
        return content

    def _resolve_short_link(self) -> None:
        """Follow a Confluence tiny-link (``/wiki/x/<token>``) redirect once and
        replace ``self.url`` with the resolved long URL.

        Must be called after :meth:`validate_auth` so ``self.client`` is set.
        No-op for non-short-link URLs.
        """
        if not is_short_link(self.url) or self.client is None:
            return
        with timed("confluence.resolve_short_link"):
            resp = self.client.session.get(self.url, allow_redirects=True, timeout=30)
            resp.raise_for_status()
        resolved = resp.url
        if resolved and resolved != self.url:
            self.log(f"🔗 Resolved short link {self.url} → {resolved}")
            self.url = resolved

    def default_filename(self) -> str:
        if is_short_link(self.url):
            # Short link cannot be resolved yet (no auth at this point); fall
            # back to the token so auto-output still produces a usable name.
            _, token = parse_short_link(self.url)
            return f"confluence-{token}"
        _, page_id = parse_confluence_url(self.url)
        return f"confluence-{page_id}"

    def fetch(self) -> dict:
        if self.client is None:
            raise RuntimeError("Confluence client not initialized")

        _, page_id = parse_confluence_url(self.url)
        with timed("confluence.get_root_page"):
            root_page = self.client.get_page(page_id)
        if self.recursive:
            with timed("confluence.get_descendants"):
                descendants = self.client.get_descendants(page_id)
            pages = [root_page] + descendants
        else:
            pages = [root_page]

        return {"page_id": page_id, "pages": pages}

    def transform(self, raw: dict) -> str:
        if self.client is None:
            raise RuntimeError("Confluence client not initialized")

        page = raw["pages"][0]
        page_id = page["id"]
        title = page.get("title", "Untitled")

        html_content = page.get("body", {}).get("storage", {}).get("value")
        if html_content is None:
            page = self.client.get_page(page_id)
            html_content = page.get("body", {}).get("storage", {}).get("value", "")

        metadata_block = self._build_metadata_block(page, notes_out=self.summary.notes)
        markdown, _, marker_line_map = html_to_markdown(html_content or "", image_map={}, base_url=self.client.base_url)
        # Title "# {title}\n\n" = 2 lines; metadata block contributes its own newlines.
        offset = 2 + metadata_block.count("\n")
        marker_line_map = {ref: line + offset for ref, line in marker_line_map.items()}
        result = f"# {title}\n\n{metadata_block}{markdown}"

        comments_md = self._fetch_and_format_comments(page_id, marker_line_map=marker_line_map)
        if comments_md:
            result += f"\n\n---\n\n## Comments\n\n{comments_md}"

        return result

    def dump(self) -> None:
        if self.obsidian_mode:
            self._dump_obsidian()
            return

        self.summary = Summary(source="confluence")
        self.validate_auth()
        self._resolve_short_link()
        with timed("stage.fetch"):
            raw = self.fetch()

        if not self.output:
            with timed("stage.transform"):
                content = self.transform(raw)
            self.summary.resources_fetched = 1
            self.summary.resources_rendered = 1
            self.summary.artifacts_written = 1
            sys.stdout.write(content)
            self._emit_and_manifest()
            return

        output_path = Path(self.output)
        output_path.mkdir(parents=True, exist_ok=True)

        if self.client is None:
            raise RuntimeError("Confluence client not initialized")

        global_attachment_pool: dict[str, str] = {}
        pool_lock = threading.Lock()

        with timed("stage.export_pages"):
            results = parallel_map(
                lambda page: self._export_page(
                    page_data=page,
                    output_dir=output_path,
                    global_attachment_pool=global_attachment_pool,
                    pool_lock=pool_lock,
                ),
                raw["pages"],
            )

        # Aggregate worker results in the main thread (thread-safe).
        # Workers return ExportResult objects; they do NOT mutate self.summary.
        for result in results:
            self.summary.add_export_result(result)
        self.summary.resources_fetched = len(raw["pages"])
        self.summary.artifacts_written = self.summary.resources_rendered

        self.log(f"✅ Export completed: {self.summary.resources_rendered}/{self.summary.resources_fetched} pages")
        if self.summary.skipped:
            self.log(f"  → {self.summary.skipped} empty page(s) skipped")
        if self.summary.failed:
            self.warn(f"  ✗ {self.summary.failed} page(s) failed")
        self.log(f"📁 Output: {output_path}")

        self._emit_and_manifest()

    def _dump_obsidian(self) -> None:
        self.summary = Summary(source="confluence")
        from ctxd.obsidian import (
            build_attachment_refs,
            refresh_attachments,
            resolve_attachments_base_dir,
            resolve_attachments_dir_rel,
            sanitize_note_stem,
            wrap_with_frontmatter,
        )

        self.validate_auth()
        self._resolve_short_link()
        if self.client is None:
            raise RuntimeError("Confluence client not initialized")

        _, page_id = parse_confluence_url(self.url)
        page = self.client.get_page(page_id)
        title = str(page.get("title", "Untitled"))
        self.summary.resources_fetched = 1

        if self.output:
            output_path = Path(self.output)
        else:
            stem = sanitize_note_stem(title, fallback=f"confluence-{page_id}")
            output_path = Path.cwd() / f"{stem}.md"

        attachments_dir_rel = resolve_attachments_dir_rel()
        if attachments_dir_rel.is_absolute():
            attachments_dir_abs = attachments_dir_rel
        else:
            base = resolve_attachments_base_dir(output_path)
            attachments_dir_abs = base / attachments_dir_rel

        html_content = page.get("body", {}).get("storage", {}).get("value") or ""

        obsidian_notes: list[str] = []

        try:
            attachments_meta = self.client.get_attachments(page_id)
        except Exception as exc:
            self.warn(f"⚠ Failed to fetch attachments for {page_id}: {exc}")
            self.summary.failed += 1
            obsidian_notes.append(f"attachments fetch failed: {exc}")
            attachments_meta = []

        refs = build_attachment_refs(page_id, attachments_meta, attachments_dir_rel)
        referenced_images = set(extract_confluence_images(html_content))

        if self.all_attachments:
            download_names = set(refs.keys())
        else:
            download_names = referenced_images & set(refs.keys())

        image_map: dict[str, str] = {
            name: refs[name].target_rel_path
            for name in referenced_images
            if name in refs
        }

        metadata_block = self._build_metadata_block(page, notes_out=obsidian_notes)
        markdown, _, marker_line_map = html_to_markdown(
            html_content, image_map=image_map, base_url=self.client.base_url
        )
        offset = 2 + metadata_block.count("\n")
        marker_line_map = {ref: line + offset for ref, line in marker_line_map.items()}
        body = f"# {title}\n\n{metadata_block}{markdown}"

        comments_md = self._fetch_and_format_comments(
            page_id, marker_line_map=marker_line_map, notes_out=obsidian_notes,
        )
        if comments_md:
            body += f"\n\n---\n\n## Comments\n\n{comments_md}"

        content = wrap_with_frontmatter(body, "confluence", self.url, title)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        self.log(f"✅ Saved to {output_path}")
        self.summary.resources_rendered = 1
        self.summary.artifacts_written = 1
        self.summary.notes.extend(obsidian_notes)

        desired_refs = [refs[name] for name in sorted(download_names)]
        if desired_refs:
            try:
                count = refresh_attachments(
                    self.client, page_id, desired_refs, attachments_dir_abs
                )
                self.log(f"📎 Refreshed {count} attachments in {attachments_dir_abs}")
            except Exception as exc:
                self.warn(f"⚠ Attachment refresh failed: {exc}")
                self.summary.failed += 1
                self.summary.add_note(f"attachment refresh failed: {exc}")

        # Pass output_path explicitly so manifest is written even when
        # self.output is None (auto-naming with -O).
        self._emit_and_manifest(manifest_path=output_path)

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        sanitized = re.sub(r'[<>:"|?*\\/]', "", name)
        sanitized = re.sub("[\x00-\x1f]", "", sanitized)
        sanitized = re.sub(r"\s+", " ", sanitized).strip()
        return sanitized or "Untitled"

    def _export_page(
        self,
        page_data: dict,
        output_dir: Path,
        global_attachment_pool: dict[str, str],
        pool_lock: threading.Lock,
    ) -> ExportResult:
        """Export a single page.  Returns an ``ExportResult`` (thread-safe).

        Does NOT mutate ``self.summary`` — the caller aggregates results
        in the main thread to avoid concurrent access.
        """
        if self.client is None:
            raise RuntimeError("Confluence client not initialized")

        page_id = str(page_data.get("id", "unknown"))
        title = page_data.get("title", "Untitled")
        worker_notes: list[str] = []

        try:
            html_content = page_data.get("body", {}).get("storage", {}).get("value")
            if html_content is None:
                full_page = self.client.get_page(page_id)
                html_content = full_page.get("body", {}).get("storage", {}).get("value", "")

            if not html_content or not html_content.strip():
                self.warn(f"  → Skipping empty page: {title}")
                return ExportResult(
                    status=PageStatus.SKIPPED, page_id=page_id,
                    title=title, reason="empty page body",
                )

            safe_title = self._sanitize_filename(title)
            page_dir = output_dir / f"{page_id}_{safe_title}"
            page_dir.mkdir(parents=True, exist_ok=True)

            if self.debug:
                raw_path = page_dir / "raw.html"
                raw_path.write_text(html_content, encoding="utf-8")

            image_map: dict[str, str] = {}
            if self.include_images:
                with timed("stage.attachments"):
                    image_map = self._download_page_images(
                        page_id=page_id,
                        page_html=html_content,
                        page_dir=page_dir,
                        global_attachment_pool=global_attachment_pool,
                        pool_lock=pool_lock,
                        notes_out=worker_notes,
                    )

            base_url = self.client.base_url if self.client else None
            metadata_block = self._build_metadata_block(page_data, notes_out=worker_notes)
            with timed("stage.transform"):
                markdown, _, marker_line_map = html_to_markdown(html_content, image_map=image_map, base_url=base_url)
            offset = 2 + metadata_block.count("\n")
            marker_line_map = {ref: line + offset for ref, line in marker_line_map.items()}
            markdown = f"# {title}\n\n{metadata_block}{markdown}"

            with timed("stage.comments"):
                comments_md = self._fetch_and_format_comments(
                    page_id, marker_line_map=marker_line_map, notes_out=worker_notes,
                )
            if comments_md:
                markdown += f"\n\n---\n\n## Comments\n\n{comments_md}"

            (page_dir / "README.md").write_text(markdown, encoding="utf-8")
            self.log(f"  ✓ Saved: {page_dir / 'README.md'}")
            return ExportResult(
                status=PageStatus.WRITTEN, page_id=page_id, title=title,
                notes=worker_notes,
            )
        except Exception as exc:
            self.warn(f"  ✗ Failed to export page {page_id}: {exc}")
            return ExportResult(
                status=PageStatus.FAILED, page_id=page_id,
                title=title, reason=str(exc), notes=worker_notes,
            )

    def _fetch_and_format_comments(
        self,
        page_id: str,
        marker_line_map: dict[str, int] | None = None,
        notes_out: list[str] | None = None,
    ) -> str:
        if self.client is None:
            return ""
        resolve_user = self.client.get_user_display_name
        client = self.client

        def attach_children(comments: list[dict], comment_type: str) -> None:
            if not comments:
                return
            results = parallel_map(
                lambda c: client.get_comment_children(c["id"], comment_type=comment_type),
                comments,
            )
            for comment, children in zip(comments, results):
                if children:
                    comment["_children"] = children

        parts: list[str] = []
        try:
            inline_comments = client.get_inline_comments(page_id)
            attach_children(inline_comments, "inline")
            if inline_comments:
                parts.append("### Inline Comments\n")
                parts.append(comments_to_markdown(inline_comments, resolve_user=resolve_user, marker_line_map=marker_line_map))
        except Exception as exc:
            self.warn(f"    ⚠ Failed to fetch inline comments for page {page_id}: {exc}")
            if notes_out is not None:
                notes_out.append(f"inline comments failed (page {page_id}): {exc}")

        try:
            footer_comments = client.get_footer_comments(page_id)
            attach_children(footer_comments, "footer")
            if footer_comments:
                parts.append("### Footer Comments\n")
                parts.append(comments_to_markdown(footer_comments, resolve_user=resolve_user))
        except Exception as exc:
            self.warn(f"    ⚠ Failed to fetch footer comments for page {page_id}: {exc}")
            if notes_out is not None:
                notes_out.append(f"footer comments failed (page {page_id}): {exc}")

        return "\n".join(parts)

    def _download_page_images(
        self,
        page_id: str,
        page_html: str,
        page_dir: Path,
        global_attachment_pool: dict[str, str],
        pool_lock: threading.Lock,
        notes_out: list[str] | None = None,
    ) -> dict[str, str]:
        if self.client is None:
            raise RuntimeError("Confluence client not initialized")

        def _note(msg: str) -> None:
            if notes_out is not None:
                notes_out.append(msg)

        image_map: dict[str, str] = {}
        try:
            attachments = self.client.get_attachments(page_id)
            attachment_map: dict[str, dict] = {}
            for attachment in attachments:
                filename = attachment.get("title", "")
                if filename:
                    attachment_map[filename] = attachment

            if attachment_map:
                with pool_lock:
                    global_attachment_pool.update(attachment_map)

            used_attachments: set[str]
            if self.all_attachments:
                used_attachments = set(attachment_map.keys())
            else:
                used_attachments = set(extract_confluence_images(page_html))

            image_dir = page_dir / "images"

            def resolve(filename: str) -> dict | None:
                attachment = attachment_map.get(filename)
                if attachment:
                    return attachment
                with pool_lock:
                    return global_attachment_pool.get(filename)

            download_targets: list[tuple[str, dict]] = []
            for filename in used_attachments:
                if not self._is_image_file(filename):
                    continue
                attachment = resolve(filename)
                if not attachment:
                    # Never-silent: referenced image not found in attachment map.
                    self.warn(f"    ⚠ Referenced image not found in attachments: {filename}")
                    _note(f"missing attachment: {filename}")
                    continue
                if not attachment.get("fileId"):
                    self.warn(f"    ⚠ Skipping {filename}: no fileId in attachment metadata")
                    _note(f"attachment skipped (no fileId): {filename}")
                    continue
                download_targets.append((filename, attachment))

            def download_one(target: tuple[str, dict]) -> tuple[str, bool]:
                filename, attachment = target
                try:
                    content = self.client.download_attachment(
                        file_id=attachment["fileId"],
                        page_id=attachment.get("pageId") or page_id,
                    )
                    local_path = image_dir / filename
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(local_path, "wb") as handle:
                        handle.write(content)
                    return filename, True
                except Exception as exc:
                    self.warn(f"    ⚠ Failed to download {filename}: {exc}")
                    _note(f"image download failed: {filename} ({exc})")
                    return filename, False

            for filename, ok in parallel_map(download_one, download_targets):
                if ok:
                    image_map[filename] = f"images/{filename}"

            if image_map:
                self.log(f"    ✓ Downloaded {len(image_map)} images")
        except Exception as exc:
            self.warn(f"    ⚠ Failed to process attachments for {page_id}: {exc}")
            _note(f"attachments processing failed (page {page_id}): {exc}")

        return image_map

    @staticmethod
    def _is_image_file(filename: str) -> bool:
        lowered = filename.lower()
        return lowered.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"))

    def _build_metadata_block(self, page: dict, notes_out: list[str] | None = None) -> str:
        space_id = page.get("spaceId") or ""
        if space_id and self.client is not None:
            space = self.client.get_space_name(space_id)
            # Fallback means the lookup failed (client already warned).
            if space == space_id and notes_out is not None:
                notes_out.append(f"space name lookup failed: {space_id}")
        else:
            space = space_id or "Unknown"

        author_id = page.get("authorId") or ""
        if author_id and self.client is not None:
            author = self.client.get_user_display_name(author_id)
            if author == author_id and notes_out is not None:
                notes_out.append(f"user name lookup failed: {author_id}")
        else:
            author = author_id or "Unknown"

        created = _format_iso_date(page.get("createdAt") or "")
        version = page.get("version") or {}
        last_modified = _format_iso_date(version.get("createdAt") or "")

        webui = (page.get("_links") or {}).get("webui") or ""
        if webui and self.client is not None:
            url = f"{self.client.base_url}/wiki{webui}"
        else:
            url = "Unknown"

        lines = [
            "## Metadata",
            "",
            "| Field | Value |",
            "|-------|-------|",
            f"| **Space** | {space} |",
            f"| **Author** | {author} |",
            f"| **Created** | {created} |",
            f"| **Last Modified** | {last_modified} |",
            f"| **URL** | {url} |",
            "",
            "",
        ]
        return "\n".join(lines)


def _format_iso_date(iso: str) -> str:
    if not iso:
        return "Unknown"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return iso[:10]
