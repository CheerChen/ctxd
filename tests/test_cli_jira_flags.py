from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from ctxd.cli import main
from ctxd.router import Source


class _FakeJiraDumper:
    last_instance = None

    def __init__(self, *args, **kwargs):
        self.output = kwargs.get("output")
        self.include_images = kwargs.get("include_images")
        self.all_attachments = kwargs.get("all_attachments")
        self.fmt = kwargs.get("fmt", "md")
        self.url = kwargs.get("url", "")
        self.dumped = False
        type(self).last_instance = self

    def default_filename(self) -> str:
        return "jira-DEV-42.md"

    def log(self, message: str) -> None:
        pass

    def dump(self) -> None:
        self.dumped = True


_JIRA_URL = "https://foo.atlassian.net/browse/DEV-42"


def _runner(monkeypatch) -> CliRunner:
    monkeypatch.setattr("ctxd.cli.detect", lambda _url: Source.JIRA)
    monkeypatch.setattr("ctxd.cli.JiraDumper", _FakeJiraDumper)
    return CliRunner()


def test_jira_stdout_is_default(monkeypatch) -> None:
    result = _runner(monkeypatch).invoke(main, [_JIRA_URL])

    assert result.exit_code == 0, result.output
    assert _FakeJiraDumper.last_instance.output is None
    assert _FakeJiraDumper.last_instance.all_attachments is False


def test_all_attachments_without_output_errors(monkeypatch) -> None:
    result = _runner(monkeypatch).invoke(main, [_JIRA_URL, "--all-attachments"])

    assert result.exit_code != 0
    assert "--all-attachments" in result.output
    assert "requires -o" in result.output
    assert "Try:" in result.output


def test_include_images_without_output_errors(monkeypatch) -> None:
    result = _runner(monkeypatch).invoke(main, [_JIRA_URL, "-i"])

    assert result.exit_code != 0
    assert "requires -o" in result.output


def test_all_attachments_with_auto_output_succeeds(monkeypatch) -> None:
    result = _runner(monkeypatch).invoke(main, [_JIRA_URL, "--all-attachments", "-O"])

    assert result.exit_code == 0, result.output
    assert _FakeJiraDumper.last_instance.all_attachments is True
    assert _FakeJiraDumper.last_instance.output == "jira-DEV-42.md"


def test_output_existing_directory_gets_default_filename(monkeypatch, tmp_path: Path) -> None:
    """``-o <dir>`` used to crash with 'Is a directory' at rename time."""
    result = _runner(monkeypatch).invoke(main, [_JIRA_URL, "-o", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert _FakeJiraDumper.last_instance.output == str(tmp_path / "jira-DEV-42.md")


def test_output_explicit_file_is_untouched(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "issue.md"
    result = _runner(monkeypatch).invoke(main, [_JIRA_URL, "-o", str(target)])

    assert result.exit_code == 0, result.output
    assert _FakeJiraDumper.last_instance.output == str(target)
