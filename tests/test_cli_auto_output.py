from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from ctxd.cli import main
from ctxd.router import Source


class _FakeBaseDumper:
    last_instance = None
    auto_name = "auto.out"

    def __init__(self, *args, **kwargs):
        self.output = kwargs.get("output")
        type(self).last_instance = self

    def default_filename(self) -> str:
        return type(self).auto_name

    def dump(self) -> None:
        return


class _FakeGitHubDumper(_FakeBaseDumper):
    auto_name = "pr-9.md"


class _FakeSlackDumper(_FakeBaseDumper):
    auto_name = "slack-C123-1735881234.123456.md"


class _FakeConfluenceDumper(_FakeBaseDumper):
    auto_name = "confluence-3140419873"


def test_auto_output_for_github(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("ctxd.cli.detect", lambda _url: Source.GITHUB_PR)
    monkeypatch.setattr("ctxd.cli.GitHubPRDumper", _FakeGitHubDumper)

    result = runner.invoke(main, ["-O", "https://github.com/o/r/pull/9"])

    assert result.exit_code == 0
    assert _FakeGitHubDumper.last_instance is not None
    assert _FakeGitHubDumper.last_instance.output == "pr-9.md"


def test_auto_output_for_slack(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("ctxd.cli.detect", lambda _url: Source.SLACK_THREAD)
    monkeypatch.setattr("ctxd.cli.SlackDumper", _FakeSlackDumper)

    result = runner.invoke(main, ["-O", "https://foo.slack.com/archives/C123/p1735881234123456"])

    assert result.exit_code == 0
    assert _FakeSlackDumper.last_instance is not None
    assert _FakeSlackDumper.last_instance.output == "slack-C123-1735881234.123456.md"


def test_auto_output_for_confluence_creates_directory(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("ctxd.cli.detect", lambda _url: Source.CONFLUENCE)
    monkeypatch.setattr("ctxd.cli.ConfluenceDumper", _FakeConfluenceDumper)

    with runner.isolated_filesystem():
        result = runner.invoke(main, ["-O", "https://foo.atlassian.net/wiki/spaces/ABC/pages/3140419873/title"])

        assert result.exit_code == 0
        assert _FakeConfluenceDumper.last_instance is not None
        assert _FakeConfluenceDumper.last_instance.output == "confluence-3140419873"
        assert Path("confluence-3140419873").is_dir()


def test_output_and_auto_output_are_mutually_exclusive(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("ctxd.cli.detect", lambda _url: Source.GITHUB_PR)
    monkeypatch.setattr("ctxd.cli.GitHubPRDumper", _FakeGitHubDumper)

    result = runner.invoke(main, ["-o", "pr.md", "-O", "https://github.com/o/r/pull/9"])

    assert result.exit_code != 0
    assert "mutually exclusive" in result.output
