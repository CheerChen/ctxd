from __future__ import annotations

import os
from pathlib import Path

import pytest

from ctxd import auth


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    config_path = tmp_path / "config"
    monkeypatch.setattr(auth, "CONFIG_PATH", config_path)
    auth._reset_cache_for_tests()
    for var in (
        "SLACK_TOKEN",
        "CONFLUENCE_BASE_URL",
        "CONFLUENCE_EMAIL",
        "CONFLUENCE_API_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)
    yield config_path
    auth._reset_cache_for_tests()


def _write_config(path: Path, body: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    os.chmod(path, mode)


def test_env_wins_over_file(_isolated_config, monkeypatch) -> None:
    _write_config(_isolated_config, "SLACK_TOKEN=from-file\n")
    monkeypatch.setenv("SLACK_TOKEN", "from-env")
    assert auth.get_slack_token() == "from-env"


def test_file_used_when_env_missing(_isolated_config) -> None:
    _write_config(_isolated_config, "SLACK_TOKEN=from-file\n")
    assert auth.get_slack_token() == "from-file"


def test_confluence_all_from_file(_isolated_config) -> None:
    _write_config(
        _isolated_config,
        "CONFLUENCE_BASE_URL=https://foo.atlassian.net\n"
        "CONFLUENCE_EMAIL=a@b.c\n"
        "CONFLUENCE_API_TOKEN=tok\n",
    )
    assert auth.ensure_confluence_auth() == ("https://foo.atlassian.net", "a@b.c", "tok")


def test_confluence_env_and_file_mixed(_isolated_config, monkeypatch) -> None:
    _write_config(_isolated_config, "CONFLUENCE_API_TOKEN=from-file\n")
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://env.atlassian.net")
    monkeypatch.setenv("CONFLUENCE_EMAIL", "env@b.c")
    base, email, token = auth.ensure_confluence_auth()
    assert base == "https://env.atlassian.net"
    assert email == "env@b.c"
    assert token == "from-file"


def test_missing_both_raises_with_both_options(_isolated_config) -> None:
    with pytest.raises(auth.AuthError) as exc:
        auth.ensure_confluence_auth()
    msg = str(exc.value)
    assert "env" in msg.lower()
    assert str(_isolated_config) in msg


def test_perm_warning_fires_once(_isolated_config, capsys) -> None:
    _write_config(_isolated_config, "SLACK_TOKEN=x\n", mode=0o644)
    auth.get_slack_token()
    auth.get_slack_token()
    err = capsys.readouterr().err
    assert err.count("readable by others") == 1
    assert "chmod 600" in err


def test_no_warning_when_mode_is_secure(_isolated_config, capsys) -> None:
    _write_config(_isolated_config, "SLACK_TOKEN=x\n", mode=0o600)
    auth.get_slack_token()
    err = capsys.readouterr().err
    assert "readable by others" not in err
