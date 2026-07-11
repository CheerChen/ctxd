"""Jira issue dumper."""

from __future__ import annotations

import json
from pathlib import Path

import markdownify

from ctxd.auth import ensure_jira_auth
from ctxd.dumpers.base import BaseDumper
from ctxd.jira.api_client import JiraClient
from ctxd.jira.converter import preprocess_jira_html
from ctxd.jira.url_parser import parse_jira_url
from ctxd.summary import Summary


class JiraDumper(BaseDumper):
    def __init__(
        self,
        url: str,
        output: str | None,
        fmt: str,
        quiet: bool = False,
        verbose: bool = False,
        debug: bool = False,
        obsidian_mode: bool = False,
        obsidian_auto_output: bool = False,
    ):
        super().__init__(url=url, output=output, fmt=fmt, quiet=quiet, verbose=verbose)
        self.client: JiraClient | None = None
        self.issue_key: str = ""
        self.debug = debug
        self.obsidian_mode = obsidian_mode
        self.obsidian_auto_output = obsidian_auto_output

    def dump(self) -> None:
        if not self.obsidian_mode:
            super().dump()
            return

        from ctxd.obsidian import sanitize_note_stem, wrap_with_frontmatter

        self.summary = Summary(source="jira")
        self.validate_auth()
        raw = self.fetch()
        key = raw["key"]
        summary = raw["fields"].get("summary", "Untitled")
        title = f"[{key}] {summary}"

        if self.output:
            output_path = Path(self.output)
        else:
            stem = sanitize_note_stem(title, fallback=f"jira-{key}")
            output_path = Path.cwd() / f"{stem}.md"

        body = self.transform(raw)
        content = wrap_with_frontmatter(body, "jira", self.url, title)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        self.log(f"✅ Saved to {output_path}")
        self.summary.resources_rendered = 1
        self.summary.artifacts_written = 1
        self._emit_and_manifest(manifest_path=output_path)

    def validate_auth(self) -> None:
        base_url, email, token = ensure_jira_auth()
        self.client = JiraClient(base_url=base_url, email=email, api_token=token)

    def default_filename(self) -> str:
        _, issue_key = parse_jira_url(self.url)
        ext = "md" if self.fmt == "md" else "txt"
        return f"jira-{issue_key}.{ext}"

    def fetch(self) -> dict:
        self.summary.source = "jira"
        self.summary.resources_fetched = 1
        if self.client is None:
            raise RuntimeError("Jira client not initialized")

        _, self.issue_key = parse_jira_url(self.url)
        issue = self.client.get_issue(self.issue_key)
        comments = self.client.get_comments(self.issue_key)

        if comments:
            self.summary.add_note(f"{len(comments)} comments")

        fields = issue.get("fields", {})
        rendered = issue.get("renderedFields", {})
        names = issue.get("names", {})

        # Discover custom fields (rich-text + plain serializable).
        # Omitted fields are recorded in the summary so the user knows
        # data was dropped — never silent.
        custom_fields, omitted_fields = _extract_custom_fields(fields, rendered, names)
        if self.verbose and custom_fields:
            for cf in custom_fields:
                self.log(f"  📋 Custom field: {cf['name']} ({cf['key']}) [{cf['type']}]")
        if omitted_fields:
            self.warn(f"  ⚠ {len(omitted_fields)} custom field(s) omitted (unsupported type):")
            for om in omitted_fields:
                self.warn(f"    - {om['name']} ({om['key']}): {om['reason']}")
                self.summary.add_note(
                    f"custom field omitted: {om['name']} ({om['key']}) — {om['reason']}"
                )

        result = {
            "key": issue.get("key", self.issue_key),
            "fields": fields,
            "rendered": rendered,
            "names": names,
            "custom_fields": custom_fields,
            "comments": comments,
        }

        if self.debug and self.output:
            self._save_debug_html(issue, comments)

        return result

    def transform(self, raw: dict) -> str:
        key = raw["key"]
        fields = raw["fields"]
        rendered = raw["rendered"]
        comments = raw["comments"]
        custom_fields = raw.get("custom_fields", [])

        summary = fields.get("summary", "Untitled")
        status = _nested_name(fields.get("status"))
        priority = _nested_name(fields.get("priority"))
        issue_type = _nested_name(fields.get("issuetype"))
        assignee = _display_name(fields.get("assignee"))
        reporter = _display_name(fields.get("reporter"))
        labels = fields.get("labels", [])
        components = [c.get("name", "") for c in (fields.get("components") or [])]
        created = fields.get("created", "")
        updated = fields.get("updated", "")
        site, _ = parse_jira_url(self.url)
        issue_url = f"{site}/browse/{key}"

        # Description: prefer rendered HTML → markdown, fallback to plain text
        description_html = rendered.get("description", "")
        if description_html:
            description = _html_to_md(description_html)
        else:
            description = fields.get("description") or "(No description)"

        # Subtasks
        subtasks = fields.get("subtasks") or []

        # Linked issues
        issue_links = fields.get("issuelinks") or []

        if self.fmt == "md":
            return self._format_markdown(
                key=key,
                summary=summary,
                status=status,
                priority=priority,
                issue_type=issue_type,
                assignee=assignee,
                reporter=reporter,
                labels=labels,
                components=components,
                created=created,
                updated=updated,
                issue_url=issue_url,
                description=description,
                custom_fields=custom_fields,
                subtasks=subtasks,
                issue_links=issue_links,
                comments=comments,
                rendered_comments=rendered,
            )

        return self._format_text(
            key=key,
            summary=summary,
            status=status,
            priority=priority,
            issue_type=issue_type,
            assignee=assignee,
            reporter=reporter,
            labels=labels,
            components=components,
            created=created,
            updated=updated,
            issue_url=issue_url,
            description=description,
            custom_fields=custom_fields,
            subtasks=subtasks,
            issue_links=issue_links,
            comments=comments,
            rendered_comments=rendered,
        )

    def _format_markdown(
        self,
        *,
        key: str,
        summary: str,
        status: str,
        priority: str,
        issue_type: str,
        assignee: str,
        reporter: str,
        labels: list[str],
        components: list[str],
        created: str,
        updated: str,
        issue_url: str,
        description: str,
        custom_fields: list[dict],
        subtasks: list[dict],
        issue_links: list[dict],
        comments: list[dict],
        rendered_comments: dict,
    ) -> str:
        lines = [
            f"# [{key}] {summary}",
            "",
            "## Metadata",
            "",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| **Type** | {issue_type} |",
            f"| **Status** | {status} |",
            f"| **Priority** | {priority} |",
            f"| **Assignee** | {assignee} |",
            f"| **Reporter** | {reporter} |",
            f"| **Labels** | {', '.join(labels) if labels else 'None'} |",
            f"| **Components** | {', '.join(components) if components else 'None'} |",
            f"| **Created** | {created} |",
            f"| **Updated** | {updated} |",
            f"| **URL** | {issue_url} |",
            "",
            "## Description",
            "",
            description,
            "",
        ]

        for cf in custom_fields:
            lines.append(f"## {cf['name']}")
            lines.append("")
            lines.append(cf["content"])
            lines.append("")

        if subtasks:
            lines.append("## Subtasks")
            lines.append("")
            for st in subtasks:
                st_key = st.get("key", "")
                st_summary = st.get("fields", {}).get("summary", "")
                st_status = _nested_name(st.get("fields", {}).get("status"))
                lines.append(f"- **{st_key}**: {st_summary} [{st_status}]")
            lines.append("")

        if issue_links:
            lines.append("## Linked Issues")
            lines.append("")
            for link in issue_links:
                link_type = link.get("type", {}).get("outward", "relates to")
                target = link.get("outwardIssue") or link.get("inwardIssue")
                if target:
                    t_key = target.get("key", "")
                    t_summary = target.get("fields", {}).get("summary", "")
                    t_status = _nested_name(target.get("fields", {}).get("status"))
                    lines.append(f"- {link_type} **{t_key}**: {t_summary} [{t_status}]")
            lines.append("")

        if comments:
            lines.append("## Comments")
            lines.append("")
            rendered_comment_list = rendered_comments.get("comment", {}).get("comments", [])
            for i, comment in enumerate(comments):
                author = _display_name(comment.get("author"))
                created_at = comment.get("created", "")
                lines.append(f"### {author} — {created_at}")
                lines.append("")
                # Prefer rendered body
                rendered_body = ""
                if i < len(rendered_comment_list):
                    rendered_body = rendered_comment_list[i].get("renderedBody", "")
                if not rendered_body:
                    rendered_body = comment.get("renderedBody", "")
                if rendered_body:
                    body_md = _html_to_md(rendered_body)
                else:
                    body_md = comment.get("body", "(empty)")
                lines.append(_blockquote(body_md))
                lines.append("")

        return "\n".join(lines)

    def _format_text(
        self,
        *,
        key: str,
        summary: str,
        status: str,
        priority: str,
        issue_type: str,
        assignee: str,
        reporter: str,
        labels: list[str],
        components: list[str],
        created: str,
        updated: str,
        issue_url: str,
        description: str,
        custom_fields: list[dict],
        subtasks: list[dict],
        issue_links: list[dict],
        comments: list[dict],
        rendered_comments: dict,
    ) -> str:
        lines = [
            "################################################################################",
            f"# JIRA ISSUE: [{key}] {summary}",
            "################################################################################",
            "",
            "--- METADATA ---",
            f"Type:       {issue_type}",
            f"Status:     {status}",
            f"Priority:   {priority}",
            f"Assignee:   {assignee}",
            f"Reporter:   {reporter}",
            f"Labels:     {', '.join(labels) if labels else 'None'}",
            f"Components: {', '.join(components) if components else 'None'}",
            f"Created:    {created}",
            f"Updated:    {updated}",
            f"URL:        {issue_url}",
            "",
            "--- DESCRIPTION ---",
            description,
            "",
        ]

        for cf in custom_fields:
            lines.append(f"--- {cf['name'].upper()} ---")
            lines.append(cf["content"])
            lines.append("")

        if subtasks:
            lines.append("--- SUBTASKS ---")
            for st in subtasks:
                st_key = st.get("key", "")
                st_summary = st.get("fields", {}).get("summary", "")
                st_status = _nested_name(st.get("fields", {}).get("status"))
                lines.append(f"  {st_key}: {st_summary} [{st_status}]")
            lines.append("")

        if issue_links:
            lines.append("--- LINKED ISSUES ---")
            for link in issue_links:
                link_type = link.get("type", {}).get("outward", "relates to")
                target = link.get("outwardIssue") or link.get("inwardIssue")
                if target:
                    t_key = target.get("key", "")
                    t_summary = target.get("fields", {}).get("summary", "")
                    t_status = _nested_name(target.get("fields", {}).get("status"))
                    lines.append(f"  {link_type} {t_key}: {t_summary} [{t_status}]")
            lines.append("")

        if comments:
            lines.append("--- COMMENTS ---")
            lines.append("")
            rendered_comment_list = rendered_comments.get("comment", {}).get("comments", [])
            for i, comment in enumerate(comments):
                author = _display_name(comment.get("author"))
                created_at = comment.get("created", "")
                lines.append(f"[{author}] {created_at}")
                rendered_body = ""
                if i < len(rendered_comment_list):
                    rendered_body = rendered_comment_list[i].get("renderedBody", "")
                if not rendered_body:
                    rendered_body = comment.get("renderedBody", "")
                if rendered_body:
                    body_md = _html_to_md(rendered_body)
                else:
                    body_md = comment.get("body", "(empty)")
                for body_line in body_md.splitlines():
                    lines.append(f"    {body_line}")
                lines.append("")

        return "\n".join(lines)

    def _save_debug_html(self, issue: dict, comments: list[dict]) -> None:
        """Save raw API responses for debugging conversion issues."""
        output_path = Path(self.output) if self.output else None
        if not output_path:
            return

        debug_path = output_path.with_suffix(".debug.html")
        rendered = issue.get("renderedFields", {})

        parts = ["<!-- JIRA DEBUG: Raw rendered HTML from API -->\n"]

        # Description
        desc_html = rendered.get("description", "")
        if desc_html:
            parts.append("<h1>== RENDERED DESCRIPTION ==</h1>\n")
            parts.append(desc_html)
            parts.append("\n\n")

        # Comments
        rendered_comments = rendered.get("comment", {}).get("comments", [])
        for i, comment in enumerate(comments):
            author = _display_name(comment.get("author"))
            parts.append(f"<h1>== COMMENT {i + 1}: {author} ==</h1>\n")
            rendered_body = ""
            if i < len(rendered_comments):
                rendered_body = rendered_comments[i].get("renderedBody", "")
            if not rendered_body:
                rendered_body = comment.get("renderedBody", "")
            parts.append(rendered_body or "(no rendered body)")
            parts.append("\n\n")

        debug_path.write_text("".join(parts), encoding="utf-8")
        self.log(f"🔍 Debug HTML saved to {debug_path}")


def _nested_name(obj: dict | None) -> str:
    if not obj:
        return "None"
    return obj.get("name", "Unknown")


def _display_name(obj: dict | None) -> str:
    if not obj:
        return "Unassigned"
    return obj.get("displayName", obj.get("name", "Unknown"))


def _extract_custom_fields(
    fields: dict, rendered: dict, names: dict
) -> tuple[list[dict], list[dict]]:
    """Discover custom fields from renderedFields and raw fields.

    Returns ``(custom_fields, omitted_fields)``:

    - ``custom_fields``: rich-text fields (HTML rendered) and plain
      serializable fields (str/int/float/bool/list/dict).  Each entry has
      ``key``, ``name``, ``content`` (markdown string), and ``type``
      (``"richtext"`` or ``"plain"``).
    - ``omitted_fields``: fields that could not be serialized (e.g. complex
      nested user/group objects with no rendered form).  Each entry has
      ``key``, ``name``, and ``reason``.  The caller should record these
      in the summary so the user knows data was dropped.
    """
    custom_fields: list[dict] = []
    omitted_fields: list[dict] = []
    seen_keys: set[str] = set()

    # 1. Rich-text fields from renderedFields (existing behavior).
    for key, value in rendered.items():
        if not key.startswith("customfield_"):
            continue
        if not isinstance(value, str) or "<" not in value:
            continue
        name = names.get(key, key)
        content = _html_to_md(value)
        if content:
            custom_fields.append({"key": key, "name": name, "content": content, "type": "richtext"})
            seen_keys.add(key)

    # 2. Non-rich-text custom fields from raw fields.
    #    Export serializable values (str/int/float/bool/simple lists/dicts).
    #    Record complex nested objects as omitted.
    for key, value in fields.items():
        if not key.startswith("customfield_"):
            continue
        if key in seen_keys:
            continue
        if value is None:
            continue
        name = names.get(key, key)

        # Try to produce a readable string representation.
        rendered_value = _serialize_plain_field(value)
        if rendered_value is not None:
            custom_fields.append({
                "key": key, "name": name,
                "content": rendered_value, "type": "plain",
            })
        else:
            omitted_fields.append({
                "key": key, "name": name,
                "reason": f"unsupported type: {type(value).__name__}",
            })

    return custom_fields, omitted_fields


def _serialize_plain_field(value) -> str | None:
    """Convert a non-rich-text Jira field value to a readable string.

    Returns None if the value is too complex to serialize meaningfully
    (e.g. nested user/group objects with multiple sub-fields).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value if value.strip() else None
    if isinstance(value, list):
        # List of strings or simple dicts — join each element.
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                # Simple dict: try name/key/value/summary fields.
                simple = _simple_dict_to_str(item)
                if simple:
                    parts.append(simple)
                else:
                    return None  # Too complex
            else:
                return None
        return "\n".join(parts) if parts else None
    if isinstance(value, dict):
        simple = _simple_dict_to_str(value)
        return simple
    return None


def _simple_dict_to_str(d: dict) -> str | None:
    """Extract a readable string from a dict with common Jira key names."""
    for field in ("name", "key", "value", "summary", "displayName"):
        v = d.get(field)
        if isinstance(v, str) and v.strip():
            return v
    # If the dict has only one string value, use it.
    str_values = [v for v in d.values() if isinstance(v, str) and v.strip()]
    if len(str_values) == 1:
        return str_values[0]
    return None


def _blockquote(text: str) -> str:
    """Prefix every line with '> ' for markdown blockquote."""
    return "\n".join(f"> {line}" for line in text.splitlines())


def _html_to_md(html: str) -> str:
    html = preprocess_jira_html(html)
    return markdownify.markdownify(
        html,
        heading_style="ATX",
        bullets="*",
        strip=["script", "style"],
    ).strip()
