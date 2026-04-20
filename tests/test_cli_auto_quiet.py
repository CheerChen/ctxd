from __future__ import annotations

from click.testing import CliRunner

from ctxd.cli import main
from ctxd.router import Source


class _FakeGitHubDumper:
    last_instance = None

    def __init__(self, *args, **kwargs):
        self.output = kwargs.get("output")
        self.quiet = kwargs.get("quiet")
        self.verbose = kwargs.get("verbose")
        type(self).last_instance = self

    def default_filename(self) -> str:
        return "pr-1.md"

    def dump(self) -> None:
        return


def test_auto_quiet_when_stderr_not_a_tty(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("ctxd.cli.detect", lambda _url: Source.GITHUB_PR)
    monkeypatch.setattr("ctxd.cli.GitHubPRDumper", _FakeGitHubDumper)
    monkeypatch.setattr("ctxd.cli._stderr_is_tty", lambda: False)

    result = runner.invoke(main, ["https://github.com/o/r/pull/1"])

    assert result.exit_code == 0, result.output
    assert _FakeGitHubDumper.last_instance.quiet is True


def test_explicit_verbose_defeats_auto_quiet(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("ctxd.cli.detect", lambda _url: Source.GITHUB_PR)
    monkeypatch.setattr("ctxd.cli.GitHubPRDumper", _FakeGitHubDumper)
    monkeypatch.setattr("ctxd.cli._stderr_is_tty", lambda: False)

    result = runner.invoke(main, ["https://github.com/o/r/pull/1", "-v"])

    assert result.exit_code == 0, result.output
    assert _FakeGitHubDumper.last_instance.quiet is False


def test_no_auto_quiet_when_stderr_is_a_tty(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("ctxd.cli.detect", lambda _url: Source.GITHUB_PR)
    monkeypatch.setattr("ctxd.cli.GitHubPRDumper", _FakeGitHubDumper)
    monkeypatch.setattr("ctxd.cli._stderr_is_tty", lambda: True)

    result = runner.invoke(main, ["https://github.com/o/r/pull/1"])

    assert result.exit_code == 0, result.output
    assert _FakeGitHubDumper.last_instance.quiet is False
