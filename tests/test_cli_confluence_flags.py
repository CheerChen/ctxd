from __future__ import annotations

from click.testing import CliRunner

from ctxd.cli import main
from ctxd.router import Source


class _FakeConfluenceDumper:
    last_instance = None

    def __init__(self, *args, **kwargs):
        self.output = kwargs.get("output")
        self.recursive = kwargs.get("recursive")
        self.include_images = kwargs.get("include_images")
        self.all_attachments = kwargs.get("all_attachments")
        self.quiet = kwargs.get("quiet")
        type(self).last_instance = self

    def default_filename(self) -> str:
        return "confluence-123"

    def dump(self) -> None:
        return


_CONF_URL = "https://foo.atlassian.net/wiki/spaces/ABC/pages/123/title"


def test_confluence_stdout_single_page_is_default(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("ctxd.cli.detect", lambda _url: Source.CONFLUENCE)
    monkeypatch.setattr("ctxd.cli.ConfluenceDumper", _FakeConfluenceDumper)

    result = runner.invoke(main, [_CONF_URL])

    assert result.exit_code == 0, result.output
    assert _FakeConfluenceDumper.last_instance.recursive is False
    assert _FakeConfluenceDumper.last_instance.include_images is False
    assert _FakeConfluenceDumper.last_instance.output is None


def test_confluence_recursive_without_output_errors(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("ctxd.cli.detect", lambda _url: Source.CONFLUENCE)
    monkeypatch.setattr("ctxd.cli.ConfluenceDumper", _FakeConfluenceDumper)

    result = runner.invoke(main, [_CONF_URL, "-r"])

    assert result.exit_code != 0
    assert "-r" in result.output
    assert "requires -o" in result.output
    assert "Try:" in result.output


def test_confluence_include_images_without_output_errors(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("ctxd.cli.detect", lambda _url: Source.CONFLUENCE)
    monkeypatch.setattr("ctxd.cli.ConfluenceDumper", _FakeConfluenceDumper)

    result = runner.invoke(main, [_CONF_URL, "-i"])

    assert result.exit_code != 0
    assert "-i" in result.output
    assert "requires -o" in result.output


def test_confluence_recursive_with_output_succeeds(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    monkeypatch.setattr("ctxd.cli.detect", lambda _url: Source.CONFLUENCE)
    monkeypatch.setattr("ctxd.cli.ConfluenceDumper", _FakeConfluenceDumper)

    out = tmp_path / "export"
    result = runner.invoke(main, [_CONF_URL, "-r", "-i", "-o", str(out)])

    assert result.exit_code == 0, result.output
    assert _FakeConfluenceDumper.last_instance.recursive is True
    assert _FakeConfluenceDumper.last_instance.include_images is True
    assert out.is_dir()
