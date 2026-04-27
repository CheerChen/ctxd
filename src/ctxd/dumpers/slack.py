"""Slack thread dumper."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from urllib.parse import urlsplit

import requests

from ctxd.auth import get_slack_token
from ctxd.dumpers.base import BaseDumper
from ctxd.router import parse_slack_thread_url


class SlackDumper(BaseDumper):
    def __init__(
        self,
        url: str,
        output: str | None,
        fmt: str,
        quiet: bool = False,
        verbose: bool = False,
        download_files: bool = False,
        raw: bool = False,
    ):
        super().__init__(url=url, output=output, fmt=fmt, quiet=quiet, verbose=verbose)
        self.download_files = download_files
        self.raw = raw
        self.token = ""
        self.session = requests.Session()

    def default_filename(self) -> str:
        channel_id, thread_ts = parse_slack_thread_url(self.url)
        ext = "md" if self.fmt == "md" else "txt"
        return f"slack-{channel_id}-{thread_ts}.{ext}"

    def validate_auth(self) -> None:
        self.token = get_slack_token()
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})

    def fetch(self) -> dict:
        channel, thread_ts = parse_slack_thread_url(self.url)
        messages = self._fetch_thread_messages(channel, thread_ts)
        if not messages:
            raise RuntimeError("No messages found in Slack thread.")

        participants = sorted({m.get("user") for m in messages if m.get("user")})
        channel_name = self._get_channel_name(channel)

        return {
            "channel": channel,
            "channel_name": channel_name,
            "thread_ts": thread_ts,
            "messages": messages,
            "participants": participants,
        }

    def transform(self, raw: dict) -> str:
        channel = raw["channel"]
        channel_name = raw["channel_name"]
        thread_ts = raw["thread_ts"]
        messages = raw["messages"]
        participants = raw["participants"]

        start_time = self._format_ts(messages[0].get("ts", thread_ts))

        lines: list[str] = []
        if self.fmt == "md":
            lines.append(f"# Slack Thread: {channel}-{thread_ts}")
            lines.append("")
            lines.append(f"**Channel:** #{channel_name} ({channel})")
            lines.append(f"**Channel URL:** {self._channel_url(channel)}")
            lines.append(f"**Thread Started:** {start_time}")
            lines.append(f"**Thread URL:** {self._thread_url(channel, thread_ts)}")
            lines.append("")
            lines.append(f"## Participants ({len(participants)})")
            lines.extend(self._format_participant_lines(participants, markdown=True))
            lines.append("")
            lines.append("## Conversation")
            lines.append("")
        else:
            lines.append("################################################################################")
            lines.append(f"# SLACK THREAD: {channel}-{thread_ts}")
            lines.append("################################################################################")
            lines.append(f"Channel: #{channel_name} ({channel})")
            lines.append(f"Channel URL: {self._channel_url(channel)}")
            lines.append(f"Thread Started: {start_time}")
            lines.append(f"Thread URL: {self._thread_url(channel, thread_ts)}")
            lines.append("")
            lines.append(f"--- PARTICIPANTS ({len(participants)}) ---")
            lines.extend(self._format_participant_lines(participants, markdown=False))
            lines.append("")
            lines.append("--- CONVERSATION ---")
            lines.append("")

        attachment_base_dir = Path(self.output).parent if self.output else Path.cwd()

        for msg in messages:
            lines.extend(
                self._format_message(
                    msg,
                    markdown=self.fmt == "md",
                    attachment_base_dir=attachment_base_dir,
                )
            )

        return "\n".join(lines).strip() + "\n"

    def _api_call(self, method: str, params: dict[str, str]) -> dict:
        url = f"https://slack.com/api/{method}"
        resp = self.session.post(url, data=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("ok"):
            error = payload.get("error", "unknown_error")
            needed = payload.get("needed")
            provided = payload.get("provided")
            details = f"Slack API {method} failed: {error}"
            if needed:
                details += f" (needed: {needed})"
            if provided:
                details += f" (provided: {provided})"
            raise RuntimeError(details)
        return payload

    def _fetch_thread_messages(self, channel: str, thread_ts: str) -> list[dict]:
        messages: list[dict] = []
        cursor = ""

        while True:
            params = {
                "channel": channel,
                "ts": thread_ts,
                "limit": "200",
                "inclusive": "true",
            }
            if cursor:
                params["cursor"] = cursor

            payload = self._api_call("conversations.replies", params)
            messages.extend(payload.get("messages", []))

            cursor = payload.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break

        return messages

    def _get_user(self, user_id: str) -> dict:
        try:
            payload = self._api_call("users.info", {"user": user_id})
            user = payload.get("user", {})
            profile = user.get("profile", {})
            return {
                "id": user.get("id", user_id),
                "display_name": profile.get("display_name_normalized") or profile.get("display_name") or "",
                "name": profile.get("real_name_normalized")
                or profile.get("real_name")
                or user.get("real_name")
                or user.get("name")
                or user_id,
                "is_bot": bool(user.get("is_bot", False)),
            }
        except Exception:
            return {
                "id": user_id,
                "display_name": "",
                "name": user_id,
                "is_bot": False,
            }

    def _get_channel_name(self, channel_id: str) -> str:
        try:
            payload = self._api_call("conversations.info", {"channel": channel_id})
            channel = payload.get("channel", {})
            return channel.get("name") or channel_id
        except Exception:
            return channel_id

    def _format_participant_lines(self, participants: list[str], markdown: bool) -> list[str]:
        lines: list[str] = []
        for uid in participants:
            user = self._get_user(uid)
            name = user.get("name") or uid
            display_name = user.get("display_name") or ""
            label = f"@{name}"
            if display_name and display_name != name:
                label = f"@{display_name} ({name})"
            if user.get("is_bot"):
                label += " [BOT]"
            lines.append(f"- {label}")
        return lines

    def _format_message(self, msg: dict, markdown: bool, attachment_base_dir: Path) -> list[str]:
        ts = msg.get("ts", "")
        text = msg.get("text", "")
        files = msg.get("files", []) or []
        user_id = msg.get("user")
        bot_name = msg.get("bot_profile", {}).get("name") or msg.get("username")

        if user_id:
            user = self._get_user(user_id)
            display_name = f"@{self._conversation_user_name(user, user_id)}"
        elif bot_name:
            display_name = f"@{bot_name} [BOT]"
        else:
            display_name = "@unknown"

        processed = self._convert_special_mentions(text)
        processed = self._convert_user_mentions(processed)
        processed = self._convert_channel_mentions(processed)
        processed = self._convert_links(processed, markdown=markdown)
        if markdown and not self.raw:
            processed = self._convert_mrkdwn_to_markdown(processed)

        lines: list[str] = []
        if markdown:
            lines.append(f"### [{display_name}] {self._format_ts(ts)}")
            lines.append(processed)
        else:
            lines.append(f"[{display_name}] {self._format_ts(ts)}")
            lines.append(processed)

        if files:
            if markdown:
                lines.append("")
                lines.append("**Attachments:**")
                for file in files:
                    name = file.get("name", "attachment")
                    mimetype = file.get("mimetype", "unknown")
                    permalink = file.get("permalink") or file.get("url_private") or "n/a"
                    lines.append(f"- 📎 [{name}] ({mimetype}) - {permalink}")
            else:
                lines.append("")
                lines.append("Attachments:")
                for file in files:
                    name = file.get("name", "attachment")
                    mimetype = file.get("mimetype", "unknown")
                    permalink = file.get("permalink") or file.get("url_private") or "n/a"
                    lines.append(f"  📎 [{name}] ({mimetype}) - {permalink}")

            if self.download_files:
                self._download_files(files, attachment_base_dir)

        lines.append("")
        lines.append("---")
        lines.append("")
        return lines

    def _download_files(self, files: list[dict], attachment_base_dir: Path) -> None:
        attachment_dir = attachment_base_dir / "attachments"
        attachment_dir.mkdir(parents=True, exist_ok=True)

        for file in files:
            url = file.get("url_private")
            name = file.get("name", "attachment")
            if not url:
                continue

            try:
                resp = self.session.get(url, timeout=60)
                resp.raise_for_status()
                target = attachment_dir / name
                target.write_bytes(resp.content)
                self.log(f"  📥 Downloaded: {name}")
            except Exception as exc:
                self.log(f"  ⚠ Failed to download {name}: {exc}")

    @staticmethod
    def _format_ts(ts: str) -> str:
        try:
            epoch = float(ts)
            return dt.datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return ts

    @staticmethod
    def _convert_special_mentions(text: str) -> str:
        return (
            text.replace("<!here>", "@here")
            .replace("<!channel>", "@channel")
            .replace("<!everyone>", "@everyone")
        )

    def _convert_user_mentions(self, text: str) -> str:
        pattern = re.compile(r"<@([UW][A-Z0-9]+)(?:\|[^>]+)?>")

        def replace(match: re.Match[str]) -> str:
            uid = match.group(1)
            user = self._get_user(uid)
            username = self._conversation_user_name(user, uid)
            return f"@{username}"

        return pattern.sub(replace, text)

    def _convert_channel_mentions(self, text: str) -> str:
        pattern = re.compile(r"<#([CG][A-Z0-9]+)(?:\|([^>]+))?>")

        def replace(match: re.Match[str]) -> str:
            cid = match.group(1)
            label = match.group(2) or self._get_channel_name(cid)
            return f"#{label}"

        return pattern.sub(replace, text)

    @staticmethod
    def _convert_links(text: str, markdown: bool) -> str:
        if markdown:
            text = re.sub(r"<(https?://[^|>]+)\|([^>]+)>", r"[\2](\1)", text)
        else:
            text = re.sub(r"<(https?://[^|>]+)\|([^>]+)>", r"\2 (\1)", text)
        return re.sub(r"<(https?://[^>]+)>", r"\1", text)

    @staticmethod
    def _convert_mrkdwn_to_markdown(text: str) -> str:
        text = SlackDumper._convert_slack_list_markers(text)
        text = re.sub(r"\*([^\n*]+)\*", r"**\1**", text)
        text = re.sub(r"_([^\n_]+)_", r"*\1*", text)
        text = re.sub(r"~([^\n~]+)~", r"~~\1~~", text)
        return text

    @staticmethod
    def _conversation_user_name(user: dict, fallback: str) -> str:
        return user.get("name") or fallback

    def _channel_url(self, channel: str) -> str:
        parsed = urlsplit(self.url)
        base_url = (
            f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else "https://slack.com"
        )
        team_match = re.search(r"/client/([^/]+)/", parsed.path)
        if team_match:
            return f"{base_url}/client/{team_match.group(1)}/{channel}"
        return f"{base_url}/archives/{channel}"

    def _thread_url(self, channel: str, thread_ts: str) -> str:
        parsed = urlsplit(self.url)
        base_url = (
            f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else "https://slack.com"
        )
        team_match = re.search(r"/client/([^/]+)/", parsed.path)
        if team_match:
            return f"{base_url}/client/{team_match.group(1)}/{channel}/thread/{channel}-{thread_ts}"
        return f"{base_url}/archives/{channel}/{self._thread_permalink_token(thread_ts)}"

    @staticmethod
    def _thread_permalink_token(thread_ts: str) -> str:
        return f"p{thread_ts.replace('.', '')}"

    @staticmethod
    def _convert_slack_list_markers(text: str) -> str:
        bullet_levels = {"\u2022": 0, "\u25e6": 1, "\u25aa": 2, "\u2023": 1}
        marker_re = re.compile(
            r"^(?P<indent>[ \t]*)(?P<marker>[\u2022\u25e6\u25aa\u2023])\s+(?P<body>.*)$"
        )
        in_code_block = False
        lines: list[str] = []

        for line in text.splitlines():
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                lines.append(line)
                continue

            if in_code_block:
                lines.append(line)
                continue

            match = marker_re.match(line)
            if not match:
                lines.append(line)
                continue

            indent = match.group("indent")
            marker = match.group("marker")
            explicit_level = sum(2 if char == "\t" else 1 for char in indent) // 2
            level = max(explicit_level, bullet_levels[marker])
            lines.append(f"{'  ' * level}- {match.group('body')}")

        trailing_newline = "\n" if text.endswith("\n") else ""
        return "\n".join(lines) + trailing_newline
