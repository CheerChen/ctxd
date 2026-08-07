from __future__ import annotations

from click.testing import CliRunner

from ctxd.cli import main
from ctxd.dumpers import DUMPERS
from ctxd.router import Source


class _FakeGitHubDumper:
    last_instance = None

    def __init__(self, *args, **kwargs):
        self.output = kwargs.get("output")
        self.quiet = kwargs.get("quiet")
        self.url = kwargs.get("url", "")
        self.fmt = kwargs.get("fmt", "md")
        type(self).last_instance = self

    def default_filename(self) -> str:
        return "pr-9.md"

    def render(self) -> str:
        return "fake content\n"

    def log(self, message: str) -> None:
        pass

    def dump(self) -> None:
        return


def test_supports_option_after_url(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("ctxd.cli.detect", lambda _url: Source.GITHUB_PR)
    monkeypatch.setitem(DUMPERS, Source.GITHUB_PR, _FakeGitHubDumper)

    result = runner.invoke(main, ["https://github.com/o/r/pull/9", "-q", "-O"])

    assert result.exit_code == 0
    assert _FakeGitHubDumper.last_instance is not None
    assert _FakeGitHubDumper.last_instance.quiet is True
    assert _FakeGitHubDumper.last_instance.output == "pr-9.md"


def test_init_zsh_emits_only_the_noglob_alias() -> None:
    runner = CliRunner()

    result = runner.invoke(main, ["init", "zsh"])

    assert result.exit_code == 0
    assert result.output.strip() == "alias ctxd='noglob ctxd'"


def test_init_bash_and_fish_emit_no_alias() -> None:
    """noglob is zsh-only, so other shells get a comment, not an alias.

    The output still has to be safe to `eval`, which a comment is.
    """
    runner = CliRunner()

    for shell in ("bash", "fish"):
        result = runner.invoke(main, ["init", shell])
        assert result.exit_code == 0
        assert result.output.startswith("#")
        assert "alias" not in result.output
