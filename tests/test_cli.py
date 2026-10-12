"""CLI wiring: output-path resolution, flag validation, quiet, init.

Dumpers are replaced by ``conftest.FakeDumper`` via the ``fake_source``
fixture, so these tests see exactly what the CLI hands a dumper.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from ctxd.cli import main
from ctxd.router import Source

_URLS = {
    Source.GITHUB_PR: "https://github.com/o/r/pull/9",
    Source.SLACK_THREAD: "https://foo.slack.com/archives/C123/p1735881234123456",
    Source.CONFLUENCE: "https://foo.atlassian.net/wiki/spaces/ABC/pages/123/title",
    Source.JIRA: "https://foo.atlassian.net/browse/DEV-42",
}


def _run(*args: str):
    return CliRunner().invoke(main, list(args))


# ---------------------------------------------------------------------------
# Output paths
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source", list(_URLS))
def test_stdout_is_the_default(fake_source, source) -> None:
    cls = fake_source(source)

    result = _run(_URLS[source])

    assert result.exit_code == 0, result.output
    dumper = cls.instances[-1]
    assert dumper.output is None
    assert not dumper.kwargs.get("recursive") and not dumper.kwargs.get("include_images")
    assert not dumper.kwargs.get("all_attachments") and not dumper.kwargs.get("download_files")


@pytest.mark.parametrize("source, name", [
    (Source.GITHUB_PR, "pr-9.md"),
    (Source.SLACK_THREAD, "slack-C123-1735881234.123456.md"),
])
def test_auto_output_uses_the_dumpers_default_filename(fake_source, source, name) -> None:
    cls = fake_source(source, name)

    result = _run("-O", _URLS[source])

    assert result.exit_code == 0, result.output
    assert cls.instances[-1].output == name


def test_confluence_auto_output_creates_a_directory(fake_source) -> None:
    cls = fake_source(Source.CONFLUENCE, "confluence-123")
    runner = CliRunner()

    with runner.isolated_filesystem():
        result = runner.invoke(main, ["-O", _URLS[Source.CONFLUENCE]])

        assert result.exit_code == 0, result.output
        assert cls.instances[-1].output == "confluence-123"
        assert Path("confluence-123").is_dir()


def test_output_and_auto_output_are_mutually_exclusive(fake_source) -> None:
    fake_source(Source.GITHUB_PR)

    result = _run("-o", "pr.md", "-O", _URLS[Source.GITHUB_PR])

    assert result.exit_code != 0
    assert "mutually exclusive" in result.output


def test_options_may_follow_the_url(fake_source) -> None:
    cls = fake_source(Source.GITHUB_PR, "pr-9.md")

    result = _run(_URLS[Source.GITHUB_PR], "-q", "-O")

    assert result.exit_code == 0, result.output
    assert (cls.instances[-1].quiet, cls.instances[-1].output) == (True, "pr-9.md")


def test_output_existing_directory_gets_the_default_filename(fake_source, tmp_path: Path) -> None:
    """``-o <dir>`` used to crash with 'Is a directory' at rename time."""
    cls = fake_source(Source.JIRA, "jira-DEV-42.md")

    result = _run(_URLS[Source.JIRA], "-o", str(tmp_path))

    assert result.exit_code == 0, result.output
    assert cls.instances[-1].output == str(tmp_path / "jira-DEV-42.md")


def test_output_explicit_file_is_untouched(fake_source, tmp_path: Path) -> None:
    cls = fake_source(Source.JIRA)
    target = tmp_path / "issue.md"

    result = _run(_URLS[Source.JIRA], "-o", str(target))

    assert result.exit_code == 0, result.output
    assert cls.instances[-1].output == str(target)


def test_confluence_output_with_suffix_is_a_file(fake_source, tmp_path: Path) -> None:
    cls = fake_source(Source.CONFLUENCE)
    target = tmp_path / "out" / "page.md"

    result = _run(_URLS[Source.CONFLUENCE], "-o", str(target))

    assert result.exit_code == 0, result.output
    assert cls.instances[-1].output == str(target)
    assert not target.exists()  # the CLI must not mkdir it; the dumper writes the file
    assert target.parent.is_dir()


@pytest.mark.parametrize("args", [[], ["-r", "-i"]])
def test_confluence_output_without_suffix_is_a_directory(fake_source, tmp_path: Path, args) -> None:
    cls = fake_source(Source.CONFLUENCE)
    target = tmp_path / "export"

    result = _run(_URLS[Source.CONFLUENCE], *args, "-o", str(target))

    assert result.exit_code == 0, result.output
    assert target.is_dir()
    assert cls.instances[-1].kwargs["recursive"] is ("-r" in args)
    assert cls.instances[-1].kwargs["include_images"] is ("-i" in args)


def test_confluence_recursive_with_file_output_errors(fake_source, tmp_path: Path) -> None:
    fake_source(Source.CONFLUENCE)

    result = _run(_URLS[Source.CONFLUENCE], "-r", "-o", str(tmp_path / "tree.md"))

    assert result.exit_code != 0
    assert "-r writes a directory tree" in result.output
    assert not (tmp_path / "tree.md").exists()


# ---------------------------------------------------------------------------
# Flags that write files need an output path
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source, flag", [
    (Source.CONFLUENCE, "-r"),
    (Source.CONFLUENCE, "-i"),
    (Source.JIRA, "-i"),
    (Source.JIRA, "--all-attachments"),
    (Source.SLACK_THREAD, "--download-files"),
])
def test_file_writing_flag_without_output_errors_with_a_fix(fake_source, source, flag) -> None:
    fake_source(source)

    result = _run(_URLS[source], flag)

    assert result.exit_code != 0
    assert flag in result.output and "requires -o" in result.output
    assert "Try:" in result.output


@pytest.mark.parametrize("source, flag, kwarg", [
    (Source.JIRA, "--all-attachments", "all_attachments"),
    (Source.SLACK_THREAD, "--download-files", "download_files"),
])
def test_file_writing_flag_with_auto_output_succeeds(fake_source, source, flag, kwarg) -> None:
    cls = fake_source(source, "auto.md")

    result = _run(_URLS[source], flag, "-O")

    assert result.exit_code == 0, result.output
    assert cls.instances[-1].kwargs[kwarg] is True
    assert cls.instances[-1].output == "auto.md"


# ---------------------------------------------------------------------------
# Quiet and init
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tty, args, quiet", [
    (False, [], True),       # stderr captured (agents): progress silenced automatically
    (False, ["-v"], False),  # explicit -v wins
    (True, [], False),       # interactive terminal: progress shown
])
def test_auto_quiet_follows_stderr(fake_source, monkeypatch, tty, args, quiet) -> None:
    cls = fake_source(Source.GITHUB_PR)
    monkeypatch.setattr("ctxd.cli._stderr_is_tty", lambda: tty)

    result = _run(_URLS[Source.GITHUB_PR], *args)

    assert result.exit_code == 0, result.output
    assert cls.instances[-1].quiet is quiet


def test_init_zsh_emits_only_the_noglob_alias() -> None:
    result = _run("init", "zsh")

    assert result.exit_code == 0
    assert result.output.strip() == "alias ctxd='noglob ctxd'"


@pytest.mark.parametrize("shell", ["bash", "fish"])
def test_init_other_shells_emit_a_comment_not_an_alias(shell) -> None:
    """noglob is zsh-only; the output must still be safe to ``eval``."""
    result = _run("init", shell)

    assert result.exit_code == 0
    assert result.output.startswith("#") and "alias" not in result.output
