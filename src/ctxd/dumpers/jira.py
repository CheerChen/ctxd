"""Jira issue dumper."""

from __future__ import annotations

from pathlib import Path

import markdownify
import requests

from ctxd.attachments import format_size
from ctxd.auth import ensure_jira_auth
from ctxd.concurrency import parallel_map
from ctxd.dumpers.base import BaseDumper, is_later
from ctxd.jira.api_client import JiraClient
from ctxd.jira.attachments import (
    JiraAttachment,
    parse_attachments,
    referenced_ids,
    rewrite_attachment_links,
    select_attachments,
)
from ctxd.jira.converter import preprocess_jira_html
from ctxd.jira.servicedesk import service_desk_keys, to_issue
from ctxd.jira.url_parser import is_portal_url, parse_jira_url, project_key

# Fields the --only comments header needs; the body, links and custom
# fields are not requested at all.
_HEADER_FIELDS = "summary,status,assignee,updated"


class JiraDumper(BaseDumper):
    def __init__(
        self,
        url: str,
        output: str | None,
        fmt: str,
        quiet: bool = False,
        verbose: bool = False,
        include_images: bool = False,
        all_attachments: bool = False,
        debug: bool = False,
        only_comments: bool = False,
        **kwargs,
    ):
        super().__init__(url=url, output=output, fmt=fmt, quiet=quiet, verbose=verbose, **kwargs)
        self.client: JiraClient | None = None
        self.issue_key: str = ""
        self.include_images = include_images
        self.all_attachments = all_attachments
        self.debug = debug
        self.only_comments = only_comments

    def validate_auth(self) -> None:
        base_url, email, token = ensure_jira_auth()
        self.client = JiraClient(base_url=base_url, email=email, api_token=token)

    def default_filename(self) -> str:
        _, issue_key = parse_jira_url(self.url)
        ext = "md" if self.fmt == "md" else "txt"
        # Never overwrite the full export with a comments-only one.
        suffix = ".comments" if self.only_comments else ""
        return f"jira-{issue_key}{suffix}.{ext}"

    def fetch(self) -> dict:
        self.summary.source = "jira"
        self.summary.resources_fetched = 1
        if self.client is None:
            raise RuntimeError("Jira client not initialized")

        _, self.issue_key = parse_jira_url(self.url)
        try:
            issue = self.client.get_issue(
                self.issue_key, fields=_HEADER_FIELDS if self.only_comments else None
            )
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status != 404 or not self._is_service_desk():
                raise
            return self._fetch_service_desk()
        comments = self.client.get_comments(self.issue_key)

        if comments:
            self.summary.add_note(f"{len(comments)} comments")

        if self.only_comments:
            self.summary.add_note(_ONLY_COMMENTS_NOTE)
            return {"key": issue.get("key", self.issue_key), "fields": issue.get("fields", {}),
                    "rendered": {}, "comments": comments}

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

    def _is_service_desk(self) -> bool:
        """Whether a platform-API 404 may be a portal customer's request.

        The 404 body is the same for a missing issue and a hidden one, so
        decide by project: a portal URL names a service desk outright;
        otherwise the project must be among the (cached) service desks
        visible to the caller.  An ordinary project's 404 stays a 404.
        """
        if is_portal_url(self.url):
            return True
        assert self.client is not None
        keys = service_desk_keys(self.client.base_url, self.client.get_service_desk_project_keys)
        return project_key(self.issue_key) in keys

    def _fetch_service_desk(self) -> dict:
        assert self.client is not None
        client = self.client
        key = self.issue_key
        fetchers = [client.get_request, client.get_request_comments]
        if not self.only_comments:
            fetchers.append(client.get_request_attachments)
        request, comments, *rest = parallel_map(lambda fn: fn(key), fetchers)
        attachments = rest[0] if rest else []
        raw = to_issue(client.base_url, request, comments, attachments)
        self.log(f"🎫 {key}: read through the service desk customer API")
        self.summary.add_note(
            "read via service desk customer API (no Browse permission): "
            "portal view only, internal comments and agent-only fields not included"
        )
        if raw["comments"]:
            self.summary.add_note(f"{len(raw['comments'])} comments")
        if self.only_comments:
            self.summary.add_note(_ONLY_COMMENTS_NOTE)
            raw.pop("request_fields")
            return raw

        custom_fields: list[dict] = []
        for field in raw.pop("request_fields"):
            if field["html"]:
                content = _html_to_md(field["html"])
            else:
                content = _serialize_plain_field(field["value"])
            if content:
                custom_fields.append(
                    {"key": field["key"], "name": field["name"], "content": content, "type": "request"}
                )
            elif field["value"] not in (None, "", []):
                reason = f"unsupported type: {type(field['value']).__name__}"
                self.warn(f"  ⚠ request field omitted: {field['name']} ({field['key']}): {reason}")
                self.summary.add_note(f"request field omitted: {field['name']} ({field['key']}) — {reason}")
        raw["custom_fields"] = custom_fields
        raw["names"] = {}

        if self.debug and self.output:
            self._save_debug_html({"renderedFields": raw["rendered"]}, raw["comments"])
        return raw

    def transform(self, raw: dict) -> str:
        if self.only_comments:
            return self._format_comments_only(raw)
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
        issue_url = raw.get("url") or f"{site}/browse/{key}"

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

        attachments = parse_attachments(fields)
        local_paths = self._download_attachments(attachments, rendered, custom_fields)

        if self.fmt == "md":
            content = self._format_markdown(
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
                attachments=attachments,
                attachment_paths=local_paths,
            )
            return rewrite_attachment_links(content, local_paths)

        content = self._format_text(
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
            attachments=attachments,
            attachment_paths=local_paths,
        )
        return rewrite_attachment_links(content, local_paths)

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
        attachments: list[JiraAttachment] | None = None,
        attachment_paths: dict[str, str] | None = None,
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
                link_type, target = _issue_link_parts(link)
                if target:
                    t_key = target.get("key", "")
                    t_summary = target.get("fields", {}).get("summary", "")
                    t_status = _nested_name(target.get("fields", {}).get("status"))
                    lines.append(f"- {link_type} **{t_key}**: {t_summary} [{t_status}]")
            lines.append("")

        if attachments:
            lines.append("## Attachments")
            lines.append("")
            for att in attachments:
                target = (attachment_paths or {}).get(att.id) or att.content_url
                meta = f"{att.mime_type or 'unknown'}, {format_size(att.size)}"
                lines.append(f"- [{att.filename}]({target}) — {meta}")
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
                lines.append(_blockquote(_comment_body(comment, i, rendered_comment_list)))
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
        attachments: list[JiraAttachment] | None = None,
        attachment_paths: dict[str, str] | None = None,
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
                link_type, target = _issue_link_parts(link)
                if target:
                    t_key = target.get("key", "")
                    t_summary = target.get("fields", {}).get("summary", "")
                    t_status = _nested_name(target.get("fields", {}).get("status"))
                    lines.append(f"  {link_type} {t_key}: {t_summary} [{t_status}]")
            lines.append("")

        if attachments:
            lines.append("--- ATTACHMENTS ---")
            for att in attachments:
                target = (attachment_paths or {}).get(att.id) or att.content_url
                meta = f"{att.mime_type or 'unknown'}, {format_size(att.size)}"
                lines.append(f"  {att.filename} ({meta}): {target}")
            lines.append("")

        if comments:
            lines.append("--- COMMENTS ---")
            lines.append("")
            rendered_comment_list = rendered_comments.get("comment", {}).get("comments", [])
            for i, comment in enumerate(comments):
                author = _display_name(comment.get("author"))
                created_at = comment.get("created", "")
                lines.append(f"[{author}] {created_at}")
                body_md = _comment_body(comment, i, rendered_comment_list)
                for body_line in body_md.splitlines():
                    lines.append(f"    {body_line}")
                lines.append("")

        return "\n".join(lines)

    def _format_comments_only(self, raw: dict) -> str:
        """Header the reader can judge staleness by, then the comments."""
        key = raw["key"]
        fields = raw["fields"]
        comments = raw["comments"]
        site, _ = parse_jira_url(self.url)
        updated = fields.get("updated", "")
        latest = max((c.get("updated") or c.get("created") or "" for c in comments), default="")
        header = [
            ("Status", _nested_name(fields.get("status"))),
            ("Assignee", _display_name(fields.get("assignee"))),
            ("Updated", updated),
            ("Latest comment", latest or "None"),
            ("URL", raw.get("url") or f"{site}/browse/{key}"),
        ]
        notice = [ONLY_COMMENTS_NOTICE]
        if is_later(updated, latest):
            notice.append(
                "The issue was updated after its latest comment: the description, status or "
                "other fields may have changed. Re-run without --only comments to see them."
            )

        title = f"[{key}] {fields.get('summary', 'Untitled')}"
        if self.fmt == "md":
            lines = [f"# {title}", ""]
            lines += [f"- **{name}:** {value}" for name, value in header]
            lines += ["", *(f"> {n}" for n in notice), "", f"## Comments ({len(comments)})", ""]
            if not comments:
                lines += ["No comments.", ""]
            for comment in comments:
                lines.append(f"### {_display_name(comment.get('author'))} — {_comment_time(comment)}")
                lines.append("")
                lines.append(_blockquote(_comment_body(comment)))
                lines.append("")
            return "\n".join(lines)

        rule = "#" * 80
        lines = [rule, f"# JIRA ISSUE: {title}", rule, ""]
        lines += [f"{name + ':':<16}{value}" for name, value in header]
        lines += ["", *notice, "", f"--- COMMENTS ({len(comments)}) ---", ""]
        if not comments:
            lines += ["No comments.", ""]
        for comment in comments:
            lines.append(f"[{_display_name(comment.get('author'))}] {_comment_time(comment)}")
            lines += [f"    {line}" for line in _comment_body(comment).splitlines()]
            lines.append("")
        return "\n".join(lines)

    def _attachment_target(self) -> tuple[Path, str] | None:
        """Return ``(absolute_dir, relative_prefix)`` for downloaded files.

        File output gets a sibling ``<stem>_attachments/`` directory.  Returns
        None when the output is stdout (nothing to be relative to).
        """
        if not self.output:
            return None
        out = Path(self.output)
        directory = out.parent / f"{out.stem}_attachments"
        return directory, directory.name

    def _download_attachments(
        self, attachments: list[JiraAttachment], rendered: dict, custom_fields: list[dict]
    ) -> dict[str, str]:
        """Download the selected attachments and return ``{id: rel_path}``."""
        if not attachments:
            return {}

        rendered_comments = rendered.get("comment", {}).get("comments", [])
        referenced = referenced_ids(
            rendered.get("description", ""),
            *(c.get("content", "") for c in custom_fields),
            *(c.get("renderedBody", "") for c in rendered_comments),
        )
        selected = select_attachments(
            attachments, referenced, self.include_images, self.all_attachments
        )

        if not selected:
            # Never silent: the issue has attachments the output does not
            # include, so say how to get them.
            if self.include_images or self.all_attachments:
                self.summary.add_note(
                    f"{len(attachments)} attachment(s) present, none matched the download filter"
                )
            else:
                self.summary.add_note(
                    f"{len(attachments)} attachment(s) not downloaded "
                    f"(use --all-attachments, or -i for referenced images, with -o/-O)"
                )
            return {}

        target = self._attachment_target()
        if target is None:
            self.warn("⚠ Attachment download needs -o <file> or -O; skipping")
            self.summary.add_note("attachments skipped: no output path")
            return {}

        if self.client is None:
            raise RuntimeError("Jira client not initialized")

        attachments_dir, rel_prefix = target
        attachments_dir.mkdir(parents=True, exist_ok=True)

        from ctxd.dumpers.base import _atomic_write_bytes

        client = self.client

        def download_one(att: JiraAttachment) -> tuple[JiraAttachment, str | None]:
            """Runs in a worker thread — returns the error instead of touching
            ``self.summary``, which the main thread aggregates below."""
            try:
                content = client.download_attachment(
                    att.id, content_url=att.content_url, max_bytes=self.max_file_size
                )
                self.run_budget.check_and_reserve(len(content))
                _atomic_write_bytes(attachments_dir / att.target_name(), content)
            except Exception as exc:
                return att, str(exc)
            return att, None

        local_paths: dict[str, str] = {}
        for att, error in parallel_map(download_one, selected):
            if error is not None:
                self.warn(f"  ⚠ Failed to download attachment {att.filename}: {error}")
                self.summary.failed += 1
                self.summary.add_note(f"attachment download failed: {att.filename} — {error}")
                continue
            local_paths[att.id] = f"{rel_prefix}/{att.target_name()}"

        if local_paths:
            self.log(f"📎 Downloaded {len(local_paths)} attachment(s) to {attachments_dir}")
            self.summary.add_note(
                f"{len(local_paths)} attachment(s) downloaded to {attachments_dir}"
            )
        return local_paths

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

        from ctxd.dumpers.base import _atomic_write_text
        _atomic_write_text(debug_path, "".join(parts))
        self.log(f"🔍 Debug HTML saved to {debug_path}")


ONLY_COMMENTS_NOTICE = (
    "Comments only: the description, fields, links and attachments are not included."
)
_ONLY_COMMENTS_NOTE = "--only comments: description, fields, links and attachments not exported"


def _comment_body(comment: dict, index: int = 0, rendered_list: list[dict] | None = None) -> str:
    """Markdown body of a comment: rendered HTML if any, else the raw body."""
    rendered_body = ""
    if rendered_list and index < len(rendered_list):
        rendered_body = rendered_list[index].get("renderedBody", "")
    if not rendered_body:
        rendered_body = comment.get("renderedBody", "")
    if rendered_body:
        return _html_to_md(rendered_body)
    return comment.get("body", "(empty)")


def _comment_time(comment: dict) -> str:
    """Creation time, plus the edit time when the comment was changed later."""
    created = comment.get("created", "")
    updated = comment.get("updated", "")
    if is_later(updated, created):
        return f"{created} (edited {updated})"
    return created


def _issue_link_parts(link: dict) -> tuple[str, dict | None]:
    """Return ``(label, linked_issue)`` for an issuelinks entry.

    ``outwardIssue`` means this issue is the source, so ``type.outward``
    describes the link (e.g. "blocks"); ``inwardIssue`` means this issue
    is the target, so ``type.inward`` applies (e.g. "is blocked by").
    """
    if link.get("outwardIssue"):
        return link.get("type", {}).get("outward", "relates to"), link["outwardIssue"]
    if link.get("inwardIssue"):
        return link.get("type", {}).get("inward", "relates to"), link["inwardIssue"]
    return "", None


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
