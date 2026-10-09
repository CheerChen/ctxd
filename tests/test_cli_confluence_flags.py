from __future__ import annotations

from click.testing import CliRunner

from ctxd.cli import main
from ctxd.dumpers import DUMPERS
from ctxd.router import Source


class _FakeConfluenceDumper:
    last_instance = None

    def __init__(self, *args, **kwargs):
        self.output = kwargs.get("output")
        self.recursive = kwargs.get("recursive")
        self.include_images = kwargs.get("include_images")
        self.all_attachments = kwargs.get("all_attachments")
        self.quiet = kwargs.get("quiet")
        self.url = kwargs.get("url", "")
        self.fmt = kwargs.get("fmt", "md")
        self.verbose = kwargs.get("verbose", False)
        type(self).last_instance = self

    def default_filename(self) -> str:
        return "confluence-123"

    def render(self) -> str:
        return "fake content\n"

    def log(self, message: str) -> None:
        pass

    def dump(self) -> None:
        return


_CONF_URL = "https://foo.atlassian.net/wiki/spaces/ABC/pages/123/title"


def test_confluence_stdout_single_page_is_default(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("ctxd.cli.detect", lambda _url: Source.CONFLUENCE)
    monkeypatch.setitem(DUMPERS, Source.CONFLUENCE, _FakeConfluenceDumper)

    result = runner.invoke(main, [_CONF_URL])

    assert result.exit_code == 0, result.output
    assert _FakeConfluenceDumper.last_instance.recursive is False
    assert _FakeConfluenceDumper.last_instance.include_images is False
    assert _FakeConfluenceDumper.last_instance.output is None


def test_confluence_recursive_without_output_errors(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("ctxd.cli.detect", lambda _url: Source.CONFLUENCE)
    monkeypatch.setitem(DUMPERS, Source.CONFLUENCE, _FakeConfluenceDumper)

    result = runner.invoke(main, [_CONF_URL, "-r"])

    assert result.exit_code != 0
    assert "-r" in result.output
    assert "requires -o" in result.output
    assert "Try:" in result.output


def test_confluence_include_images_without_output_errors(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("ctxd.cli.detect", lambda _url: Source.CONFLUENCE)
    monkeypatch.setitem(DUMPERS, Source.CONFLUENCE, _FakeConfluenceDumper)

    result = runner.invoke(main, [_CONF_URL, "-i"])

    assert result.exit_code != 0
    assert "-i" in result.output
    assert "requires -o" in result.output


def test_confluence_recursive_with_output_succeeds(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    monkeypatch.setattr("ctxd.cli.detect", lambda _url: Source.CONFLUENCE)
    monkeypatch.setitem(DUMPERS, Source.CONFLUENCE, _FakeConfluenceDumper)

    out = tmp_path / "export"
    result = runner.invoke(main, [_CONF_URL, "-r", "-i", "-o", str(out)])

    assert result.exit_code == 0, result.output
    assert _FakeConfluenceDumper.last_instance.recursive is True
    assert _FakeConfluenceDumper.last_instance.include_images is True
    assert out.is_dir()


def _invoke(monkeypatch, args):
    monkeypatch.setattr("ctxd.cli.detect", lambda _url: Source.CONFLUENCE)
    monkeypatch.setitem(DUMPERS, Source.CONFLUENCE, _FakeConfluenceDumper)
    return CliRunner().invoke(main, [_CONF_URL, *args])


def test_output_with_suffix_is_a_file_not_a_directory(monkeypatch, tmp_path) -> None:
    target = tmp_path / "out" / "page.md"

    result = _invoke(monkeypatch, ["-o", str(target)])

    assert result.exit_code == 0, result.output
    assert _FakeConfluenceDumper.last_instance.output == str(target)
    assert not target.exists()  # the CLI must not mkdir it; the dumper writes the file
    assert target.parent.is_dir()


def test_output_without_suffix_stays_a_directory(monkeypatch, tmp_path) -> None:
    target = tmp_path / "export"

    result = _invoke(monkeypatch, ["-o", str(target)])

    assert result.exit_code == 0, result.output
    assert target.is_dir()


def test_recursive_with_file_output_errors(monkeypatch, tmp_path) -> None:
    result = _invoke(monkeypatch, ["-r", "-o", str(tmp_path / "tree.md")])

    assert result.exit_code != 0
    assert "-r writes a directory tree" in result.output
    assert not (tmp_path / "tree.md").exists()
