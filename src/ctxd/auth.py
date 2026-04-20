"""Authentication helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


class AuthError(RuntimeError):
    """Raised when authentication requirements are not satisfied."""


CONFIG_PATH = Path.home() / ".config" / "ctxd" / "config"

_config_cache: dict[str, str] | None = None
_perms_warned = False


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


def _check_config_perms(path: Path) -> None:
    global _perms_warned
    if _perms_warned:
        return
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        return
    if mode & 0o077:
        print(
            f"⚠️  {path} is readable by others (mode {mode:o}); "
            f"run: chmod 600 {path}",
            file=sys.stderr,
        )
    _perms_warned = True


def _load_config() -> dict[str, str]:
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    if not CONFIG_PATH.exists():
        _config_cache = {}
        return _config_cache
    _check_config_perms(CONFIG_PATH)
    _config_cache = _read_kv_config(CONFIG_PATH)
    return _config_cache


def _resolve(key: str) -> str:
    env_val = os.getenv(key)
    if env_val:
        return env_val
    return _load_config().get(key, "")


def _reset_cache_for_tests() -> None:
    global _config_cache, _perms_warned
    _config_cache = None
    _perms_warned = False


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
    token = _resolve("SLACK_TOKEN")
    if token:
        return token
    raise AuthError(
        "❌ Slack token not found.\n"
        '   Set env: export SLACK_TOKEN="xoxp-..."\n'
        f"   Or add to {CONFIG_PATH}: SLACK_TOKEN=xoxp-..."
    )


def ensure_confluence_auth() -> tuple[str, str, str]:
    base_url = _resolve("CONFLUENCE_BASE_URL")
    email = _resolve("CONFLUENCE_EMAIL")
    token = _resolve("CONFLUENCE_API_TOKEN")

    if not all([base_url, email, token]):
        raise AuthError(
            "❌ Confluence credentials missing. Set via env or "
            f"{CONFIG_PATH} (keys: CONFLUENCE_BASE_URL, CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN).\n"
            '   Env example:\n'
            '     export CONFLUENCE_BASE_URL="https://xxx.atlassian.net"\n'
            '     export CONFLUENCE_EMAIL="you@example.com"\n'
            '     export CONFLUENCE_API_TOKEN="your-token"\n'
            f"   File example (chmod 600 {CONFIG_PATH}):\n"
            "     CONFLUENCE_BASE_URL=https://xxx.atlassian.net\n"
            "     CONFLUENCE_EMAIL=you@example.com\n"
            "     CONFLUENCE_API_TOKEN=your-token"
        )

    return base_url, email, token


def ensure_jira_auth() -> tuple[str, str, str]:
    return ensure_confluence_auth()
