"""Authentication helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


class AuthError(RuntimeError):
    """Raised when authentication requirements are not satisfied."""


def _read_kv_config(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def ensure_github_auth() -> None:
    if not shutil.which("gh"):
        raise AuthError("❌ GitHub CLI not found. Install: https://cli.github.com/")

    proc = subprocess.run(
        ["gh", "auth", "status"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AuthError("❌ GitHub CLI not authenticated.\n   Run: gh auth login")


def get_slack_token() -> str:
    env_token = os.getenv("SLACK_TOKEN")
    if env_token:
        return env_token

    config_path = Path.home() / ".config" / "ctxd" / "config"
    config = _read_kv_config(config_path)
    token = config.get("SLACK_TOKEN", "")
    if token:
        return token

    raise AuthError('❌ Slack token not found.\n   Set: export SLACK_TOKEN="xoxp-..."')


def ensure_confluence_auth() -> tuple[str, str, str]:
    base_url = os.getenv("CONFLUENCE_BASE_URL", "")
    email = os.getenv("CONFLUENCE_EMAIL", "")
    token = os.getenv("CONFLUENCE_API_TOKEN", "")

    if not all([base_url, email, token]):
        raise AuthError(
            "❌ Confluence credentials missing.\n"
            '   Set: export CONFLUENCE_BASE_URL="https://xxx.atlassian.net"\n'
            '        export CONFLUENCE_EMAIL="you@example.com"\n'
            '        export CONFLUENCE_API_TOKEN="your-token"'
        )

    return base_url, email, token


def ensure_jira_auth() -> tuple[str, str, str]:
    return ensure_confluence_auth()
