"""Tests for the --obsidian CLI flag validation."""

from __future__ import annotations

from click.testing import CliRunner

from ctxd.cli import main


def test_obsidian_rejects_github_pr_url() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--obsidian", "-O", "https://github.com/owner/repo/pull/1"])
    assert result.exit_code != 0
    assert "only supports Confluence and Jira" in result.output


def test_obsidian_rejects_slack_url() -> None:
    runner = CliRunner()
    result = runner.invoke(main, [
        "--obsidian", "-O",
        "https://example.slack.com/archives/C123/p1234567890123456",
    ])
    assert result.exit_code != 0
    assert "only supports Confluence and Jira" in result.output


def test_obsidian_requires_output_target() -> None:
    runner = CliRunner()
    result = runner.invoke(main, [
        "--obsidian",
        "https://x.atlassian.net/wiki/spaces/X/pages/123/Title",
    ])
    assert result.exit_code != 0
    assert "requires -o" in result.output


def test_obsidian_rejects_recursive() -> None:
    runner = CliRunner()
    result = runner.invoke(main, [
        "--obsidian", "-O", "-r",
        "https://x.atlassian.net/wiki/spaces/X/pages/123/Title",
    ])
    assert result.exit_code != 0
    assert "-r/--recursive" in result.output


def test_obsidian_rejects_text_format() -> None:
    runner = CliRunner()
    result = runner.invoke(main, [
        "--obsidian", "-O", "-f", "text",
        "https://x.atlassian.net/wiki/spaces/X/pages/123/Title",
    ])
    assert result.exit_code != 0
    assert "markdown" in result.output


def test_obsidian_rejects_unsupported_url() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--obsidian", "-O", "https://example.com/not-supported"])
    assert result.exit_code != 0
