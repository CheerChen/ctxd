"""GitHub Pull Request dumper."""

from __future__ import annotations

import re
from collections import OrderedDict
from typing import Callable

import requests

from ctxd.auth import get_github_token
from ctxd.concurrency import parallel_map
from ctxd.dumpers.base import BaseDumper
from ctxd.github.api_client import GitHubAPIError, GitHubClient
from ctxd.router import parse_github_pr_url


class GitHubPRDumper(BaseDumper):
    def __init__(
        self,
        url: str,
        output: str | None,
        fmt: str,
        quiet: bool = False,
        verbose: bool = False,
        diff_mode: str = "compact",
        clean_body: bool = True,
        no_bots: bool = False,
        **kwargs,
    ):
        super().__init__(url=url, output=output, fmt=fmt, quiet=quiet, verbose=verbose, **kwargs)
        self.diff_mode = diff_mode
        self.clean_body = clean_body
        self.no_bots = no_bots
        self.owner = ""
        self.repo = ""
        self.pr_number = ""
        self.client: GitHubClient | None = None

    def default_filename(self) -> str:
        _, _, number = parse_github_pr_url(self.url)
        ext = "md" if self.fmt == "md" else "txt"
        return f"pr-{number}.{ext}"

    def validate_auth(self) -> None:
        self.client = GitHubClient(get_github_token())
        self.owner, self.repo, self.pr_number = parse_github_pr_url(self.url)

    def fetch(self) -> dict:
        self.summary.source = "github_pr"
        self.summary.resources_fetched = 1
        # The 5 API calls below are independent reads — fan them out so the
        # slowest one (usually the diff) bounds wall time instead of summing.
        tasks: list[Callable[[], object]] = [
            lambda: self._api.get_pull(self.owner, self.repo, self.pr_number),
            self._fetch_issue_comments,
            self._fetch_diff_comments,
            self._fetch_reviews,
            self._generate_diff,
        ]
        pr_info, timeline_comments, diff_comments, reviews, diff_content = parallel_map(
            lambda fn: fn(), tasks
        )

        body = pr_info.get("body", "") or ""
        if self.clean_body:
            body = self.clean_pr_body(body)

        # Track sub-resource counts in notes so the summary is informative.
        sub_notes: list[str] = []
        if timeline_comments:
            sub_notes.append(f"{len(timeline_comments)} timeline comments")
        if diff_comments:
            sub_notes.append(f"{sum(len(v) for v in diff_comments.values())} inline comments")
        if reviews:
            sub_notes.append(f"{len(reviews)} reviews")
        if diff_content == self._NO_DIFF:
            sub_notes.append("diff: no differences or fetch error")
        for n in sub_notes:
            self.summary.add_note(n)

        return {
            "number": self.pr_number,
            "title": pr_info.get("title", ""),
            "body": body,
            "timeline_comments": timeline_comments,
            "diff_comments": diff_comments,
            "reviews": reviews,
            "diff_content": diff_content,
        }

    def transform(self, raw: dict) -> str:
        number = raw["number"]
        metadata = f"PR Title: {raw['title']}\n\nPR Body:\n{raw['body']}"

        if self.fmt == "md":
            lines = [
                f"# Pull Request Context: #{number}",
                "",
                "## Metadata",
                "",
                metadata,
                "",
            ]

            if raw["reviews"]:
                lines.extend(["## Reviews", ""])
                for review in raw["reviews"]:
                    lines.append(self._md_review_line(review))
                    if review["body"]:
                        for body_line in review["body"].splitlines():
                            lines.append(f"  {body_line}")
                    lines.append("")

            if raw["diff_comments"]:
                lines.extend(["## Inline Review Comments", ""])
                for path, entries in raw["diff_comments"].items():
                    lines.append(f"### `{path}`")
                    lines.append("")
                    for entry in entries:
                        lines.append(self._md_inline_header(entry))
                        for body_line in entry["body"].splitlines():
                            lines.append(f"  {body_line}")
                        lines.append("")

            if raw["timeline_comments"]:
                lines.extend(["## Timeline Comments", ""])
                for comment in raw["timeline_comments"]:
                    lines.append(self._md_timeline_line(comment))
                    for body_line in comment["body"].splitlines():
                        lines.append(f"  {body_line}")
                    lines.append("")

            lines.extend([
                "## Git Diff",
                "",
                "```diff",
                raw["diff_content"],
                "```",
                "",
            ])
            return "\n".join(lines)

        lines = [
            "################################################################################",
            f"# PULL REQUEST CONTEXT: #{number}",
            "################################################################################",
            "",
            "--- METADATA ---",
            metadata,
            "",
        ]

        if raw["reviews"]:
            lines.extend(["--- REVIEWS ---"])
            for review in raw["reviews"]:
                lines.append(self._md_review_line(review))
                if review["body"]:
                    for body_line in review["body"].splitlines():
                        lines.append(f"  {body_line}")
            lines.append("")

        if raw["diff_comments"]:
            lines.extend(["--- INLINE REVIEW COMMENTS ---"])
            for path, entries in raw["diff_comments"].items():
                lines.append(f"[{path}]")
                for entry in entries:
                    lines.append(self._md_inline_header(entry))
                    for body_line in entry["body"].splitlines():
                        lines.append(f"  {body_line}")
                lines.append("")

        if raw["timeline_comments"]:
            lines.extend(["--- TIMELINE COMMENTS ---"])
            for comment in raw["timeline_comments"]:
                lines.append(self._md_timeline_line(comment))
                for body_line in comment["body"].splitlines():
                    lines.append(f"  {body_line}")
            lines.append("")

        lines.extend(["--- GIT DIFF ---", raw["diff_content"], ""])
        return "\n".join(lines)

    @staticmethod
    def _author_tag(entry: dict) -> str:
        login = entry.get("login", "unknown")
        if entry.get("is_bot") and not login.endswith("[bot]"):
            return f"@{login}[bot]"
        return f"@{login}"

    def _md_review_line(self, review: dict) -> str:
        ts = review.get("submitted_at", "")
        ts_tag = f" ({ts})" if ts else ""
        return f"- {self._author_tag(review)} — **{review['state']}**{ts_tag}"

    def _md_timeline_line(self, comment: dict) -> str:
        ts = comment.get("created_at", "")
        ts_tag = f" ({ts})" if ts else ""
        return f"- {self._author_tag(comment)}{ts_tag}:"

    def _md_inline_header(self, entry: dict) -> str:
        side = entry.get("side") or "RIGHT"
        start_line = entry.get("start_line")
        line = entry.get("line")
        if start_line and line and start_line != line:
            line_tag = f"L{start_line}-{line}"
        elif line:
            line_tag = f"L{line}"
        else:
            line_tag = "L?"
        ts = entry.get("created_at", "")
        ts_tag = f" ({ts})" if ts else ""
        return f"- {self._author_tag(entry)} [{side}] {line_tag}{ts_tag}:"

    @property
    def _api(self) -> GitHubClient:
        """The client built in ``validate_auth`` — never None once fetching."""
        if self.client is None:
            raise RuntimeError("GitHub client not initialised; validate_auth() first")
        return self.client

    def _paginate(self, path: str) -> list[dict]:
        """Paginated read that degrades to an empty list, loudly.

        A missing comment page must not abort the whole PR dump, but it must
        never pass unnoticed either — hence warn() plus a summary note.
        """
        try:
            return self._api.paginate(path)
        except (GitHubAPIError, requests.RequestException, ValueError) as exc:
            self.warn(f"⚠ GitHub API call failed ({path}): {exc}")
            self.summary.failed += 1
            self.summary.add_note(f"API call failed ({path}): {exc}")
            return []

    def _is_bot(self, user: dict) -> bool:
        return (user or {}).get("type") == "Bot"

    def _fetch_issue_comments(self) -> list[dict]:
        comments = self._paginate(f"/repos/{self.owner}/{self.repo}/issues/{self.pr_number}/comments")
        result: list[dict] = []
        for comment in comments:
            body = (comment.get("body") or "").strip()
            if not body:
                continue
            user = comment.get("user") or {}
            if self.no_bots and self._is_bot(user):
                continue
            result.append({
                "login": user.get("login", "unknown"),
                "is_bot": self._is_bot(user),
                "body": body,
                "created_at": comment.get("created_at", ""),
            })
        return result

    def _fetch_diff_comments(self) -> OrderedDict[str, list[dict]]:
        comments = self._paginate(f"/repos/{self.owner}/{self.repo}/pulls/{self.pr_number}/comments")
        grouped: OrderedDict[str, list[dict]] = OrderedDict()

        for comment in comments:
            body = (comment.get("body") or "").strip()
            if not body:
                continue
            user = comment.get("user") or {}
            if self.no_bots and self._is_bot(user):
                continue

            path = comment.get("path") or "unknown"
            entry = {
                "login": user.get("login", "unknown"),
                "is_bot": self._is_bot(user),
                "body": body,
                "line": comment.get("line"),
                "start_line": comment.get("start_line"),
                "side": comment.get("side") or "RIGHT",
                "created_at": comment.get("created_at", ""),
                "in_reply_to_id": comment.get("in_reply_to_id"),
            }
            grouped.setdefault(path, []).append(entry)

        return grouped

    def _fetch_reviews(self) -> list[dict]:
        reviews = self._paginate(f"/repos/{self.owner}/{self.repo}/pulls/{self.pr_number}/reviews")
        result: list[dict] = []
        for review in reviews:
            state = review.get("state") or "COMMENTED"
            # Drop noisy PENDING drafts (author's own in-progress state).
            if state == "PENDING":
                continue
            user = review.get("user") or {}
            if self.no_bots and self._is_bot(user):
                continue
            result.append({
                "login": user.get("login", "unknown"),
                "is_bot": self._is_bot(user),
                "state": state,
                "body": (review.get("body") or "").strip(),
                "submitted_at": review.get("submitted_at", ""),
            })
        return result

    _NO_DIFF = "[No differences found or error generating diff]"

    def _generate_diff(self) -> str:
        if self.diff_mode == "stat":
            return self._generate_stat_diff()

        unified = self._fetch_unified_diff()
        if not unified.strip():
            return self._NO_DIFF
        if self.diff_mode == "full":
            return unified
        return self._generate_compact_diff(unified)

    def _fetch_unified_diff(self) -> str:
        try:
            return self._api.get_diff(self.owner, self.repo, self.pr_number)
        except (GitHubAPIError, requests.RequestException) as exc:
            self.warn(f"⚠ GitHub PR diff fetch failed: {exc}")
            self.summary.failed += 1
            self.summary.add_note(f"diff fetch failed: {exc}")
            return ""

    def _generate_stat_diff(self) -> str:
        files = self._paginate(f"/repos/{self.owner}/{self.repo}/pulls/{self.pr_number}/files")
        if not files:
            return self._NO_DIFF

        total_add = 0
        total_del = 0
        rows: list[tuple[str, int, int]] = []
        for f in files:
            name = f.get("filename", "") or ""
            add = int(f.get("additions", 0) or 0)
            dele = int(f.get("deletions", 0) or 0)
            total_add += add
            total_del += dele
            rows.append((name, add, dele))

        name_width = max((len(n) for n, _, _ in rows), default=0)
        lines = [f"{n.ljust(name_width)} | +{a}/-{d}" for n, a, d in rows]
        lines.extend([
            "",
            f"Summary: {len(rows)} file(s) changed, {total_add} insertion(s)(+), {total_del} deletion(s)(-)",
        ])
        return "\n".join(lines)

    def _generate_compact_diff(self, unified: str) -> str:
        hunk_num = 0
        lines: list[str] = []
        add_count = 0
        del_count = 0

        for line in unified.splitlines():
            file_match = re.match(r"^diff --git a/(.+) b/(.+)$", line)
            if file_match:
                hunk_num = 0
                lines.append(file_match.group(2))
                continue

            hunk_match = re.match(
                r"^@@ -(?P<old_start>\d+)(,(?P<old_count>\d+))? \+(?P<new_start>\d+)(,(?P<new_count>\d+))? @@(?P<context>.*)$",
                line,
            )
            if hunk_match:
                hunk_num += 1
                old_start = int(hunk_match.group("old_start"))
                old_count = int(hunk_match.group("old_count") or "1")
                new_start = int(hunk_match.group("new_start"))
                new_count = int(hunk_match.group("new_count") or "1")
                old_end = old_start if old_count == 0 else old_start + old_count - 1
                new_end = new_start if new_count == 0 else new_start + new_count - 1
                context = (hunk_match.group("context") or "").strip()
                change_info = f"+{new_count}/-{old_count}"

                if context:
                    lines.append(
                        f"  hunk {hunk_num}: lines {new_start}-{new_end} "
                        f"(was {old_start}-{old_end}, {change_info}) @ {context}"
                    )
                else:
                    lines.append(
                        f"  hunk {hunk_num}: lines {new_start}-{new_end} "
                        f"(was {old_start}-{old_end}, {change_info})"
                    )
                continue

            # Count actual +/- lines (not +++/--- file headers)
            if line.startswith("+") and not line.startswith("+++"):
                add_count += 1
            elif line.startswith("-") and not line.startswith("---"):
                del_count += 1

        if not lines:
            return self._NO_DIFF
        lines.extend(["", f"Summary: {add_count} insertion(s)(+), {del_count} deletion(s)(-)"])
        return "\n".join(lines)

    @staticmethod
    def clean_pr_body(text: str) -> str:
        lines = text.splitlines()
        output: list[str] = []
        in_fw = False
        depth = 0
        fname = ""
        desc = ""
        pending = False

        def count_tag(value: str, tag: str) -> int:
            return value.count(tag)

        for line in lines:
            if not in_fw and "File Walkthrough" in line and "<summary>" in line:
                in_fw = True
                depth = 1
                output.append("[File Changes]")
                continue

            if in_fw:
                depth += count_tag(line, "<details")
                depth -= count_tag(line, "</details>")

                if "<strong>" in line and "<details" not in line:
                    strong_match = re.search(r"<strong>(.*?)</strong>", line)
                    code_match = re.search(r"<code>(.*?)</code>", line)
                    fname = strong_match.group(1) if strong_match else ""
                    desc = code_match.group(1) if code_match else ""
                    pending = bool(fname)

                if pending and fname and "<a href" in line:
                    link = re.sub(r".*<a [^>]*>", "", line)
                    link = re.sub(r"</a>.*", "", link)
                    link = re.sub(r"[\s\t\r]", "", link)
                    if desc:
                        output.append(f"{fname}: {desc} ({link})")
                    else:
                        output.append(f"{fname} ({link})")
                    fname = ""
                    desc = ""
                    pending = False

                if depth <= 0:
                    in_fw = False
                    depth = 0
                    fname = ""
                    desc = ""
                    pending = False
                    output.append("")
                continue

            output.append(line)

        cleaned = "\n".join(output)
        cleaned = re.sub(r"<a [^>]*>([^<]*)</a>", r"\1", cleaned)
        cleaned = re.sub(r"<[^>]+>", "", cleaned)
        cleaned = cleaned.replace("&nbsp;", "")
        cleaned = cleaned.replace("&amp;", "&")
        cleaned_lines = [ln.rstrip() for ln in cleaned.splitlines()]

        collapsed: list[str] = []
        blank_count = 0
        for line in cleaned_lines:
            if not line.strip():
                blank_count += 1
                if blank_count <= 2:
                    collapsed.append("")
            else:
                blank_count = 0
                collapsed.append(line)

        return "\n".join(collapsed).strip()
