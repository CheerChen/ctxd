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


class JiraDumper(BaseDumper):
    def __init__(
        self,
        url: str,
        output: str | None,
        fmt: str,
        quiet: bool = False,
        verbose: bool = False,
        debug: bool = False,
    ):
        super().__init__(url=url, output=output, fmt=fmt, quiet=quiet, verbose=verbose)
        self.client: JiraClient | None = None
        self.issue_key: str = ""
        self.debug = debug

    def validate_auth(self) -> None:
        base_url, email, token = ensure_jira_auth()
        self.client = JiraClient(base_url=base_url, email=email, api_token=token)

    def default_filename(self) -> str:
        _, issue_key = parse_jira_url(self.url)
        ext = "md" if self.fmt == "md" else "txt"
        return f"jira-{issue_key}.{ext}"

    def fetch(self) -> dict:
        if self.client is None:
            raise RuntimeError("Jira client not initialized")

        _, self.issue_key = parse_jira_url(self.url)
        issue = self.client.get_issue(self.issue_key)
        comments = self.client.get_comments(self.issue_key)

        fields = issue.get("fields", {})
        rendered = issue.get("renderedFields", {})
        names = issue.get("names", {})

        # Discover custom rich-text fields
        custom_fields = _extract_custom_fields(fields, rendered, names)
        if self.verbose and custom_fields:
            for cf in custom_fields:
                self.log(f"  📋 Custom field: {cf['name']} ({cf['key']})")

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
) -> list[dict]:
    """Discover non-empty rich-text custom fields from renderedFields."""
    result = []
    for key, value in rendered.items():
        if not key.startswith("customfield_"):
            continue
        if not isinstance(value, str) or "<" not in value:
            continue
        name = names.get(key, key)
        content = _html_to_md(value)
        if content:
            result.append({"key": key, "name": name, "content": content})
    return result


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
