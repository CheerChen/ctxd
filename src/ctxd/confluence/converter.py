"""Confluence HTML-to-Markdown conversion helpers."""

from __future__ import annotations

import re
from typing import Callable, List, Tuple
from urllib.parse import quote

import markdownify


def extract_confluence_images(html: str) -> List[str]:
    filenames: list[str] = []
    filenames.extend(re.findall(r'<ri:attachment[^>]*ri:filename="([^"]+)"[^>]*/?>', html))

    drawio_macros = re.findall(
        r'<ac:structured-macro[^>]*ac:name="drawio"[^>]*>.*?</ac:structured-macro>',
        html,
        flags=re.DOTALL,
    )
    for macro in drawio_macros:
        name_match = re.search(r'<ac:parameter ac:name="diagramName">([^<]+)</ac:parameter>', macro)
        if name_match:
            filenames.append(f"{name_match.group(1)}.png")

    plantuml_macros = re.findall(
        r'<ac:structured-macro[^>]*ac:name="plantuml[^"]*"[^>]*>.*?</ac:structured-macro>',
        html,
        flags=re.DOTALL,
    )
    for macro in plantuml_macros:
        name_match = re.search(r'<ac:parameter ac:name="filename">([^<]+)</ac:parameter>', macro)
        if name_match:
            filenames.append(name_match.group(1))

    return list(set(filenames))


def convert_code_macros(html: str) -> str:
    def replace_code_block(match: re.Match[str]) -> str:
        full_tag = match.group(0)
        lang_match = re.search(r'<ac:parameter ac:name="language">([^<]+)</ac:parameter>', full_tag)
        language = lang_match.group(1) if lang_match else ""

        body_match = re.search(r'<ac:plain-text-body>(.*?)</ac:plain-text-body>', full_tag, flags=re.DOTALL)
        if not body_match:
            return full_tag

        content = body_match.group(1)
        if content.startswith("<![CDATA[") and content.endswith("]]>"):
            content = content[9:-3]

        class_attr = f' class="language-{language}"' if language else ""
        return f"<pre><code{class_attr}>{content}</code></pre>"

    pattern = r'<ac:structured-macro[^>]*ac:name="code"[^>]*>.*?</ac:structured-macro>'
    return re.sub(pattern, replace_code_block, html, flags=re.DOTALL)


def convert_confluence_images(html: str, image_map: dict[str, str]) -> str:
    def replace_ac_image(match: re.Match[str]) -> str:
        full_tag = match.group(0)
        alt_match = re.search(r'ac:alt="([^"]+)"', full_tag)
        alt = alt_match.group(1) if alt_match else ""
        filename_match = re.search(r'ri:filename="([^"]+)"', full_tag)
        if not filename_match:
            return ""

        filename = filename_match.group(1)
        src = image_map.get(filename, f"images/{filename}")
        return f'<img src="{src}" alt="{alt}" />'

    return re.sub(r"<ac:image[^>]*>.*?</ac:image>", replace_ac_image, html, flags=re.DOTALL)


def convert_drawio_macros(html: str, image_map: dict[str, str]) -> str:
    def replace_drawio(match: re.Match[str]) -> str:
        full_tag = match.group(0)
        name_match = re.search(r'<ac:parameter ac:name="diagramName">([^<]+)</ac:parameter>', full_tag)
        if not name_match:
            return ""
        diagram_name = name_match.group(1)
        png_filename = f"{diagram_name}.png"
        src = image_map.get(png_filename, f"images/{png_filename}")
        return f'<img src="{src}" alt="{diagram_name}" />'

    pattern = r'<ac:structured-macro[^>]*ac:name="drawio"[^>]*>.*?</ac:structured-macro>'
    return re.sub(pattern, replace_drawio, html, flags=re.DOTALL)


def convert_internal_links(html: str, base_url: str | None = None) -> str:
    def replace_ac_link(match: re.Match[str]) -> str:
        full_tag = match.group(0)

        body_match = re.search(
            r'<ac:(?:plain-text-)?link-body[^>]*>(.*?)</ac:(?:plain-text-)?link-body>',
            full_tag,
            flags=re.DOTALL,
        )
        title_match = re.search(r'ri:content-title="([^"]+)"', full_tag)
        space_match = re.search(r'ri:space-key="([^"]+)"', full_tag)
        attachment_match = re.search(r'<ri:attachment[^>]*ri:filename="([^"]+)"', full_tag)

        display_text = body_match.group(1).strip() if body_match else None
        if not display_text and title_match:
            display_text = title_match.group(1)
        if not display_text and attachment_match:
            display_text = attachment_match.group(1)
        if not display_text:
            display_text = full_tag

        href = ""
        if attachment_match:
            href = attachment_match.group(1)
        elif title_match and base_url:
            page_title = title_match.group(1)
            space_key = space_match.group(1) if space_match else ""
            if space_key:
                href = f"{base_url}/wiki/display/{quote(space_key)}/{quote(page_title)}"
            else:
                href = f"{base_url}/wiki/display/{quote(page_title)}"
        elif title_match:
            href = title_match.group(1)

        return f'<a href="{href}">{display_text}</a>'

    pattern = r'<ac:link[^>]*>.*?</ac:link>'
    return re.sub(pattern, replace_ac_link, html, flags=re.DOTALL)


def convert_plantuml_macros(html: str, image_map: dict[str, str]) -> str:
    def replace_plantuml(match: re.Match[str]) -> str:
        full_tag = match.group(0)
        name_match = re.search(r'<ac:parameter ac:name="filename">([^<]+)</ac:parameter>', full_tag)
        if not name_match:
            return ""
        filename = name_match.group(1)
        src = image_map.get(filename, f"images/{filename}")
        return f'<img src="{src}" alt="PlantUML diagram" />'

    pattern = r'<ac:structured-macro[^>]*ac:name="plantuml[^"]*"[^>]*>.*?</ac:structured-macro>'
    return re.sub(pattern, replace_plantuml, html, flags=re.DOTALL)


def comments_to_markdown(
    comments: list[dict],
    resolve_user: Callable[[str], str] | None = None,
    marker_line_map: dict[str, int] | None = None,
    depth: int = 0,
) -> str:
    lines: list[str] = []
    indent = "  " * depth
    prev_selection: str | None = None
    for comment in comments:
        version = comment.get("version", {})
        author_id = version.get("authorId", "unknown")
        created_at = version.get("createdAt", comment.get("createdAt", ""))

        author_name = resolve_user(author_id) if resolve_user else author_id

        # Inline comment: show annotated text as blockquote, with separator between different selections
        selection = comment.get("properties", {}).get("inline-original-selection", "")
        marker_ref = comment.get("properties", {}).get("inline-marker-ref", "")
        if selection and depth == 0:
            if prev_selection is not None:
                lines.append("---")
                lines.append("")
            line_num = marker_line_map.get(marker_ref) if marker_line_map else None
            line_info = f" (Line {line_num})" if line_num else ""
            lines.append(f"{indent}> {selection}{line_info}")
            lines.append("")
            prev_selection = selection

        body_html = comment.get("body", {}).get("storage", {}).get("value", "")
        body_md = ""
        if body_html:
            body_md = markdownify.markdownify(body_html, heading_style="ATX", strip=["script", "style"]).strip()

        header = f"{indent}**{author_name}** ({created_at})" if created_at else f"{indent}**{author_name}**"

        lines.append(header)
        if body_md:
            for line in body_md.split("\n"):
                lines.append(f"{indent}{line}")
        lines.append("")

        children = comment.get("_children", [])
        if children:
            lines.append(comments_to_markdown(children, resolve_user=resolve_user, depth=depth + 1))

    return "\n".join(lines)


_MARKER_PREFIX = "\u200bMRK"
_MARKER_SUFFIX = "MRK\u200b"


def _extract_marker_lines(html: str) -> Tuple[str, list[str]]:
    marker_refs: list[str] = []
    pattern = r'<ac:inline-comment-marker[^>]*ac:ref="([^"]+)"[^>]*>(.*?)</ac:inline-comment-marker>'

    # Repeatedly process innermost markers to handle nesting
    while re.search(pattern, html, flags=re.DOTALL):
        def replace_marker(match: re.Match[str]) -> str:
            ref = match.group(1)
            content = match.group(2)
            marker_refs.append(ref)
            return f"{_MARKER_PREFIX}{ref}{_MARKER_SUFFIX}{content}"

        html = re.sub(pattern, replace_marker, html, flags=re.DOTALL)

    return html, marker_refs


def _resolve_marker_lines(markdown: str, marker_refs: list[str]) -> Tuple[str, dict[str, int]]:
    marker_line_map: dict[str, int] = {}
    for i, line in enumerate(markdown.split("\n"), start=1):
        for ref in marker_refs:
            tag = f"{_MARKER_PREFIX}{ref}{_MARKER_SUFFIX}"
            if tag in line:
                if ref not in marker_line_map:
                    marker_line_map[ref] = i

    cleaned = markdown
    for ref in marker_refs:
        tag = f"{_MARKER_PREFIX}{ref}{_MARKER_SUFFIX}"
        cleaned = cleaned.replace(tag, "")

    return cleaned, marker_line_map


def html_to_markdown(
    html: str,
    image_map: dict[str, str] | None = None,
    base_url: str | None = None,
) -> Tuple[str, List[str], dict[str, int]]:
    if image_map is None:
        image_map = {}

    image_filenames = extract_confluence_images(html)
    html, marker_refs = _extract_marker_lines(html)
    html = convert_internal_links(html, base_url=base_url)
    html = convert_confluence_images(html, image_map)
    html = convert_drawio_macros(html, image_map)
    html = convert_code_macros(html)
    html = convert_plantuml_macros(html, image_map)

    markdown = markdownify.markdownify(html, heading_style="ATX", bullets="*", strip=["script", "style"])
    markdown, marker_line_map = _resolve_marker_lines(markdown, marker_refs)
    return markdown, image_filenames, marker_line_map
