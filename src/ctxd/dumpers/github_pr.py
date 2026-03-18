"""GitHub Pull Request dumper."""

from __future__ import annotations

import json
import re
import subprocess
from collections import OrderedDict

from ctxd.auth import ensure_github_auth
from ctxd.dumpers.base import BaseDumper
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
    ):
        super().__init__(url=url, output=output, fmt=fmt, quiet=quiet, verbose=verbose)
        self.diff_mode = diff_mode
        self.clean_body = clean_body
        self.owner = ""
        self.repo = ""
        self.pr_number = ""

    def default_filename(self) -> str:
        _, _, number = parse_github_pr_url(self.url)
        ext = "md" if self.fmt == "md" else "txt"
        return f"pr-{number}.{ext}"

    def validate_auth(self) -> None:
        ensure_github_auth()
        self.owner, self.repo, self.pr_number = parse_github_pr_url(self.url)

    def fetch(self) -> dict:
        pr_info = self._gh_json(
            [
                "pr",
                "view",
                self.pr_number,
                "--repo",
                f"{self.owner}/{self.repo}",
                "--json",
                "title,body,baseRefName,headRefName,headRefOid",
            ]
        )

        body = pr_info.get("body", "") or ""
        if self.clean_body:
            body = self.clean_pr_body(body)

        timeline_comments = self._fetch_issue_comments()
        diff_comments = self._fetch_diff_comments()
        reviews = self._fetch_reviews()

        base_branch = pr_info.get("baseRefName", "")
        head_branch = pr_info.get("headRefName", "")
        head_sha = pr_info.get("headRefOid", "")

        diff_content = self._generate_diff(base_branch, head_branch, head_sha)

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
                "## All Comments",
                "",
            ]

            if raw["timeline_comments"]:
                lines.append("### Timeline Comments")
                lines.append("")
                lines.extend(raw["timeline_comments"])
                lines.append("")

            if raw["diff_comments"]:
                lines.append("### Code Review Comments")
                lines.append("")
                for path, comments in raw["diff_comments"].items():
                    lines.append(f"#### `{path}`")
                    lines.append("")
                    lines.extend(comments)
                    lines.append("")

            if raw["reviews"]:
                lines.append("### Review Summaries")
                lines.append("")
                lines.extend(raw["reviews"])
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
            "--- ALL COMMENTS ---",
        ]

        if raw["timeline_comments"]:
            lines.extend(["", "## Timeline Comments ##", *raw["timeline_comments"]])

        if raw["diff_comments"]:
            lines.extend(["", "## Code Review Comments ##"])
            for path, comments in raw["diff_comments"].items():
                lines.append(f"[{path}]")
                lines.extend(comments)
                lines.append("")

        if raw["reviews"]:
            lines.extend(["", "## Review Summaries ##", *raw["reviews"]])

        lines.extend(["", "--- GIT DIFF ---", raw["diff_content"], ""])
        return "\n".join(lines)

    def _gh_json(self, args: list[str]) -> dict:
        cmd = ["gh", *args]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "gh command failed")
        return json.loads(proc.stdout)

    def _gh_api_paginate(self, path: str) -> list[dict]:
        cmd = ["gh", "api", "--paginate", "--slurp", path]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            return []

        try:
            pages = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return []

        flattened: list[dict] = []
        if isinstance(pages, list):
            for page in pages:
                if isinstance(page, list):
                    flattened.extend([item for item in page if isinstance(item, dict)])
                elif isinstance(page, dict):
                    flattened.append(page)
        return flattened

    def _fetch_issue_comments(self) -> list[str]:
        comments = self._gh_api_paginate(f"/repos/{self.owner}/{self.repo}/issues/{self.pr_number}/comments")
        rendered: list[str] = []
        for comment in comments:
            body = (comment.get("body") or "").strip()
            user = comment.get("user", {})
            if not body or user.get("type") == "Bot":
                continue
            login = user.get("login", "unknown")
            indented = body.replace("\n", "\n  ")
            rendered.append(f"- @{login}: {indented}")
        return rendered

    def _fetch_diff_comments(self) -> OrderedDict[str, list[str]]:
        comments = self._gh_api_paginate(f"/repos/{self.owner}/{self.repo}/pulls/{self.pr_number}/comments")
        grouped: OrderedDict[str, list[str]] = OrderedDict()

        for comment in comments:
            body = (comment.get("body") or "").strip()
            user = comment.get("user", {})
            if not body or user.get("type") == "Bot":
                continue

            path = comment.get("path") or "unknown"
            login = user.get("login", "unknown")
            line = comment.get("line")
            line_tag = f" (L{line})" if line else ""
            text = f"- @{login}{line_tag}: {body.replace(chr(10), chr(10) + '  ')}"

            if path not in grouped:
                grouped[path] = []
            grouped[path].append(text)

        return grouped

    def _fetch_reviews(self) -> list[str]:
        reviews = self._gh_api_paginate(f"/repos/{self.owner}/{self.repo}/pulls/{self.pr_number}/reviews")
        rendered: list[str] = []
        for review in reviews:
            body = (review.get("body") or "").strip()
            user = review.get("user", {})
            if not body or user.get("type") == "Bot":
                continue
            login = user.get("login", "unknown")
            state = review.get("state", "COMMENTED")
            rendered.append(f"- @{login} ({state}): {body.replace(chr(10), chr(10) + '  ')}")
        return rendered

    def _generate_diff(self, base_branch: str, head_branch: str, head_sha: str) -> str:
        if not base_branch or not head_sha:
            return "[No differences found or error generating diff]"

        self._git_fetch_if_possible(head_branch)
        self._git_fetch_if_possible(base_branch)

        diff_ref = f"origin/{base_branch}...{head_sha}"

        if self.diff_mode == "stat":
            return self._run_git(["diff", "--stat", diff_ref])
        if self.diff_mode == "full":
            return self._run_git(["diff", diff_ref])
        return self._generate_compact_diff(diff_ref)

    def _git_fetch_if_possible(self, branch: str) -> None:
        if not branch:
            return
        subprocess.run(["git", "fetch", "origin", branch], capture_output=True, text=True, check=False)

    def _run_git(self, args: list[str]) -> str:
        proc = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
        output = proc.stdout.strip()
        if proc.returncode != 0 or not output:
            return "[No differences found or error generating diff]"
        return output

    def _generate_compact_diff(self, diff_ref: str) -> str:
        proc = subprocess.run(["git", "diff", "-U0", diff_ref], capture_output=True, text=True, check=False)
        if proc.returncode != 0 or not proc.stdout.strip():
            return "[No differences found or error generating diff]"

        current_file = ""
        hunk_num = 0
        lines: list[str] = []

        for line in proc.stdout.splitlines():
            file_match = re.match(r"^diff --git a/(.+) b/(.+)$", line)
            if file_match:
                current_file = file_match.group(2)
                hunk_num = 0
                lines.append(current_file)
                continue

            hunk_match = re.match(
                r"^@@ -(?P<old_start>\d+)(,(?P<old_count>\d+))? \+(?P<new_start>\d+)(,(?P<new_count>\d+))? @@(?P<context>.*)$",
                line,
            )
            if not hunk_match:
                continue

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

        shortstat = self._run_git(["diff", "--shortstat", diff_ref])
        if shortstat and not shortstat.startswith("[No differences"):
            lines.extend(["", f"Summary: {shortstat}"])

        return "\n".join(lines) if lines else "[No differences found or error generating diff]"

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
