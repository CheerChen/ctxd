"""Confluence page dumper."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from ctxd.auth import ensure_confluence_auth
from ctxd.confluence.api_client import ConfluenceClient
from ctxd.confluence.converter import comments_to_markdown, extract_confluence_images, html_to_markdown
from ctxd.confluence.url_parser import parse_confluence_url
from ctxd.dumpers.base import BaseDumper


class ConfluenceDumper(BaseDumper):
    def __init__(
        self,
        url: str,
        output: str | None,
        fmt: str,
        quiet: bool = False,
        verbose: bool = False,
        recursive: bool = True,
        include_images: bool = True,
        all_attachments: bool = False,
        debug: bool = False,
    ):
        super().__init__(url=url, output=output, fmt=fmt, quiet=quiet, verbose=verbose)
        self.recursive = recursive
        self.include_images = include_images
        self.all_attachments = all_attachments
        self.debug = debug
        self.client: ConfluenceClient | None = None

    def validate_auth(self) -> None:
        base_url, email, token = ensure_confluence_auth()
        self.client = ConfluenceClient(base_url=base_url, email=email, api_token=token)

    def default_filename(self) -> str:
        _, page_id = parse_confluence_url(self.url)
        return f"confluence-{page_id}"

    def fetch(self) -> dict:
        if self.client is None:
            raise RuntimeError("Confluence client not initialized")

        _, page_id = parse_confluence_url(self.url)
        root_page = self.client.get_page(page_id)
        if self.recursive:
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

        markdown, _, marker_line_map = html_to_markdown(html_content or "", image_map={}, base_url=self.client.base_url)
        # Title header "# {title}\n\n" adds 2 lines offset
        marker_line_map = {ref: line + 2 for ref, line in marker_line_map.items()}
        result = f"# {title}\n\n{markdown}"

        comments_md = self._fetch_and_format_comments(page_id, marker_line_map=marker_line_map)
        if comments_md:
            result += f"\n\n---\n\n## Comments\n\n{comments_md}"

        return result

    def dump(self) -> None:
        self.validate_auth()
        raw = self.fetch()

        if not self.output:
            content = self.transform(raw)
            sys.stdout.write(content)
            return

        output_path = Path(self.output)
        output_path.mkdir(parents=True, exist_ok=True)

        if self.client is None:
            raise RuntimeError("Confluence client not initialized")

        global_attachment_pool: dict[str, str] = {}
        success = 0

        for page in raw["pages"]:
            if self._export_page(
                page_data=page,
                output_dir=output_path,
                global_attachment_pool=global_attachment_pool,
            ):
                success += 1

        self.log(f"✅ Export completed: {success}/{len(raw['pages'])} pages")
        self.log(f"📁 Output: {output_path}")

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
    ) -> bool:
        if self.client is None:
            raise RuntimeError("Confluence client not initialized")

        try:
            page_id = page_data["id"]
            title = page_data.get("title", "Untitled")

            html_content = page_data.get("body", {}).get("storage", {}).get("value")
            if html_content is None:
                full_page = self.client.get_page(page_id)
                html_content = full_page.get("body", {}).get("storage", {}).get("value", "")

            if not html_content or not html_content.strip():
                self.log(f"  → Skipping empty page: {title}")
                return True

            safe_title = self._sanitize_filename(title)
            page_dir = output_dir / f"{page_id}_{safe_title}"
            page_dir.mkdir(parents=True, exist_ok=True)

            if self.debug:
                raw_path = page_dir / "raw.html"
                raw_path.write_text(html_content, encoding="utf-8")

            image_map: dict[str, str] = {}
            if self.include_images:
                image_map = self._download_page_images(
                    page_id=page_id,
                    page_html=html_content,
                    page_dir=page_dir,
                    global_attachment_pool=global_attachment_pool,
                )

            base_url = self.client.base_url if self.client else None
            markdown, _, marker_line_map = html_to_markdown(html_content, image_map=image_map, base_url=base_url)
            marker_line_map = {ref: line + 2 for ref, line in marker_line_map.items()}
            markdown = f"# {title}\n\n{markdown}"

            comments_md = self._fetch_and_format_comments(page_id, marker_line_map=marker_line_map)
            if comments_md:
                markdown += f"\n\n---\n\n## Comments\n\n{comments_md}"

            (page_dir / "README.md").write_text(markdown, encoding="utf-8")
            self.log(f"  ✓ Saved: {page_dir / 'README.md'}")
            return True
        except Exception as exc:
            self.log(f"  ✗ Failed to export page {page_data.get('id')}: {exc}")
            return False

    def _fetch_and_format_comments(self, page_id: str, marker_line_map: dict[str, int] | None = None) -> str:
        if self.client is None:
            return ""
        resolve_user = self.client.get_user_display_name
        parts: list[str] = []
        try:
            inline_comments = self.client.get_inline_comments(page_id)
            if inline_comments:
                for comment in inline_comments:
                    children = self.client.get_comment_children(comment["id"], comment_type="inline")
                    if children:
                        comment["_children"] = children
                parts.append("### Inline Comments\n")
                parts.append(comments_to_markdown(inline_comments, resolve_user=resolve_user, marker_line_map=marker_line_map))
        except Exception as exc:
            self.log(f"    ⚠ Failed to fetch inline comments for page {page_id}: {exc}")

        try:
            footer_comments = self.client.get_footer_comments(page_id)
            if footer_comments:
                for comment in footer_comments:
                    children = self.client.get_comment_children(comment["id"], comment_type="footer")
                    if children:
                        comment["_children"] = children
                parts.append("### Footer Comments\n")
                parts.append(comments_to_markdown(footer_comments, resolve_user=resolve_user))
        except Exception as exc:
            self.log(f"    ⚠ Failed to fetch footer comments for page {page_id}: {exc}")

        return "\n".join(parts)

    def _download_page_images(
        self,
        page_id: str,
        page_html: str,
        page_dir: Path,
        global_attachment_pool: dict[str, str],
    ) -> dict[str, str]:
        if self.client is None:
            raise RuntimeError("Confluence client not initialized")

        image_map: dict[str, str] = {}
        try:
            attachments = self.client.get_attachments(page_id)
            attachment_map: dict[str, str] = {}
            for attachment in attachments:
                filename = attachment.get("title", "")
                link = attachment.get("downloadLink", "")
                if filename and link:
                    attachment_map[filename] = link

            if attachment_map:
                global_attachment_pool.update(attachment_map)

            used_attachments: set[str]
            if self.all_attachments:
                used_attachments = set(attachment_map.keys())
            else:
                used_attachments = set(extract_confluence_images(page_html))

            image_dir = page_dir / "images"

            for filename in used_attachments:
                if not self._is_image_file(filename):
                    continue
                link = attachment_map.get(filename) or global_attachment_pool.get(filename)
                if not link:
                    continue
                try:
                    content = self.client.download_attachment(link)
                    local_path = image_dir / filename
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(local_path, "wb") as handle:
                        handle.write(content)
                    image_map[filename] = f"images/{filename}"
                except Exception as exc:
                    self.log(f"    ⚠ Failed to download {filename}: {exc}")

            if image_map:
                self.log(f"    ✓ Downloaded {len(image_map)} images")
        except Exception as exc:
            self.log(f"    ⚠ Failed to process attachments for {page_id}: {exc}")

        return image_map

    @staticmethod
    def _is_image_file(filename: str) -> bool:
        lowered = filename.lower()
        return lowered.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"))
