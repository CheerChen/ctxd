from __future__ import annotations

from click.testing import CliRunner

from ctxd.cli import main
from ctxd.router import Source


class _FakeGitHubDumper:
    last_instance = None

    def __init__(self, *args, **kwargs):
        self.output = kwargs.get("output")
        self.quiet = kwargs.get("quiet")
        type(self).last_instance = self

    def default_filename(self) -> str:
        return "pr-9.md"

    def dump(self) -> None:
        return


def test_supports_option_after_url(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("ctxd.cli.detect", lambda _url: Source.GITHUB_PR)
    monkeypatch.setattr("ctxd.cli.GitHubPRDumper", _FakeGitHubDumper)

    result = runner.invoke(main, ["https://github.com/o/r/pull/9", "-q", "-o", "auto"])

    assert result.exit_code == 0
    assert _FakeGitHubDumper.last_instance is not None
    assert _FakeGitHubDumper.last_instance.quiet is True
    assert _FakeGitHubDumper.last_instance.output == "pr-9.md"


def test_init_shell_still_works() -> None:
    runner = CliRunner()

    result = runner.invoke(main, ["init", "zsh"])

    assert result.exit_code == 0
    assert result.output.strip() == "alias ctxd='noglob ctxd'\nalias ctx='noglob ctxd'"
