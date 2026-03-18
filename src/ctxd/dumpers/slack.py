"""Slack thread dumper."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path

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
        self.cache_dir = Path(os.getenv("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "ctxd"
        self.user_cache = self.cache_dir / "users.json"
        self.channel_cache = self.cache_dir / "channels.json"

    def default_filename(self) -> str:
        channel_id, thread_ts = parse_slack_thread_url(self.url)
        ext = "md" if self.fmt == "md" else "txt"
        return f"slack-{channel_id}-{thread_ts}.{ext}"

    def validate_auth(self) -> None:
        self.token = get_slack_token()
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        self._ensure_cache()

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
            lines.append(f"**Thread Started:** {start_time}")
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
            lines.append(f"Thread Started: {start_time}")
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

    def _ensure_cache(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if not self.user_cache.exists():
            self.user_cache.write_text("{}", encoding="utf-8")
        if not self.channel_cache.exists():
            self.channel_cache.write_text("{}", encoding="utf-8")

    def _read_cache(self, path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_cache(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _get_user(self, user_id: str) -> dict:
        cache = self._read_cache(self.user_cache)
        if user_id in cache:
            return cache[user_id]

        try:
            payload = self._api_call("users.info", {"user": user_id})
            user = payload.get("user", {})
            data = {
                "id": user.get("id", user_id),
                "name": user.get("name") or user_id,
                "display_name": user.get("profile", {}).get("display_name_normalized")
                or user.get("profile", {}).get("real_name_normalized")
                or user.get("real_name")
                or user.get("name")
                or user_id,
                "real_name": user.get("profile", {}).get("real_name_normalized")
                or user.get("real_name")
                or "",
                "is_bot": bool(user.get("is_bot", False)),
            }
        except Exception:
            data = {
                "id": user_id,
                "name": user_id,
                "display_name": user_id,
                "real_name": user_id,
                "is_bot": False,
            }

        cache[user_id] = data
        self._write_cache(self.user_cache, cache)
        return data

    def _get_channel_name(self, channel_id: str) -> str:
        cache = self._read_cache(self.channel_cache)
        cached = cache.get(channel_id, {}).get("name")
        if cached:
            return cached

        try:
            payload = self._api_call("conversations.info", {"channel": channel_id})
            channel = payload.get("channel", {})
            name = channel.get("name", channel_id)
            cache[channel_id] = {
                "name": name,
                "is_private": bool(channel.get("is_private", False)),
            }
            self._write_cache(self.channel_cache, cache)
            return name
        except Exception:
            return channel_id

    def _format_participant_lines(self, participants: list[str], markdown: bool) -> list[str]:
        lines: list[str] = []
        for uid in participants:
            user = self._get_user(uid)
            label = f"@{user.get('display_name') or user.get('name') or uid}"
            real_name = user.get("real_name") or ""
            if real_name:
                label += f" ({real_name})"
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
            display_name = f"@{user.get('display_name') or user.get('name') or user_id}"
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
            username = user.get("display_name") or user.get("name") or uid
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
        text = re.sub(r"\*([^*]+)\*", r"**\1**", text)
        text = re.sub(r"_([^_]+)_", r"*\1*", text)
        text = re.sub(r"~([^~]+)~", r"~~\1~~", text)
        return text
