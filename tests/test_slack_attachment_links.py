"""A downloaded Slack file must be findable from the exported artifact.

``--download-files`` saved binaries to ``attachments/`` but the Markdown kept
pointing at the Slack permalink, so nothing in the export said a local copy
existed or where it was.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from ctxd.cli import main
from ctxd.dumpers.slack import SlackDumper
from ctxd.router import Source

_URL = "https://example.slack.com/archives/C123/p1735881234123456"
_FILE = {
    "id": "F0AAAAAAA1",
    "name": "report.zip",
    "mimetype": "application/zip",
    "permalink": "https://example.slack.com/files/U1/F0AAAAAAA1/report.zip",
    "url_private_download": "https://slack.com/files/F0AAAAAAA1/dl",
}
_MSG = {"ts": "1735881234.123456", "text": "here it is", "user": "U1", "files": [_FILE]}


def _dumper(monkeypatch, tmp_path: Path, **kwargs) -> SlackDumper:
    dumper = SlackDumper(url=_URL, output=str(tmp_path / "thread.md"), fmt="md", quiet=True, **kwargs)

    def fake_get(url, timeout=60, **kw):
        class FakeResp:
            headers = {"content-type": "application/zip"}
            def raise_for_status(self): pass
            def iter_content(self, chunk_size=8192): yield b"payload"
            def close(self): pass
        return FakeResp()

    monkeypatch.setattr(dumper.session, "get", fake_get)
    monkeypatch.setattr(dumper, "_get_user", lambda uid: {"id": uid, "name": "alice", "display_name": "", "is_bot": False})
    return dumper


def _render(dumper: SlackDumper, tmp_path: Path) -> str:
    return "\n".join(
        dumper._format_message(_MSG, markdown=True, attachment_base_dir=tmp_path)
    )


def test_downloaded_file_path_is_shown_next_to_the_permalink(monkeypatch, tmp_path) -> None:
    dumper = _dumper(monkeypatch, tmp_path, download_files=True)

    rendered = _render(dumper, tmp_path)

    assert "saved: attachments/IMG_F0AAAAAAA1.zip" in rendered
    # The permalink stays — it is the address a human opens in a browser.
    assert _FILE["permalink"] in rendered


def test_no_saved_path_without_the_flag(monkeypatch, tmp_path) -> None:
    dumper = _dumper(monkeypatch, tmp_path)

    rendered = _render(dumper, tmp_path)

    assert "saved:" not in rendered
    assert _FILE["permalink"] in rendered


def test_failed_download_gets_no_saved_path(monkeypatch, tmp_path) -> None:
    dumper = _dumper(monkeypatch, tmp_path, download_files=True)
    monkeypatch.setattr(dumper.session, "get", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))

    rendered = _render(dumper, tmp_path)

    assert "saved:" not in rendered
    assert dumper.summary.failed == 1


def test_summary_reports_skipped_files(monkeypatch, tmp_path) -> None:
    dumper = _dumper(monkeypatch, tmp_path)
    dumper._files_seen = 3

    dumper._report_file_stats()

    assert any("3 file(s) not downloaded (use --download-files)" in n for n in dumper.summary.notes)


def test_summary_reports_downloaded_files(monkeypatch, tmp_path) -> None:
    dumper = _dumper(monkeypatch, tmp_path, download_files=True)
    dumper._files_seen = 2
    dumper._files_downloaded = 2
    dumper._download_dir = tmp_path / "attachments"

    dumper._report_file_stats()

    assert any("2/2 file(s) downloaded" in n for n in dumper.summary.notes)


def test_summary_silent_when_thread_has_no_files(monkeypatch, tmp_path) -> None:
    dumper = _dumper(monkeypatch, tmp_path)

    dumper._report_file_stats()

    assert dumper.summary.notes == []


# ---------------------------------------------------------------------------
# --download-files now requires an output path (was: silently wrote to cwd)
# ---------------------------------------------------------------------------

class _FakeSlackDumper:
    last_instance = None

    def __init__(self, *args, **kwargs):
        self.output = kwargs.get("output")
        self.download_files = kwargs.get("download_files")
        type(self).last_instance = self

    def default_filename(self) -> str:
        return "slack-C123-1735881234.123456.md"

    def log(self, message: str) -> None:
        pass

    def dump(self) -> None:
        return


@pytest.fixture
def runner(monkeypatch) -> CliRunner:
    monkeypatch.setattr("ctxd.cli.detect", lambda _url: Source.SLACK_THREAD)
    monkeypatch.setattr("ctxd.cli.SlackDumper", _FakeSlackDumper)
    return CliRunner()


def test_download_files_without_output_errors(runner) -> None:
    result = runner.invoke(main, [_URL, "--download-files"])

    assert result.exit_code != 0
    assert "--download-files requires -o" in result.output
    assert "Try:" in result.output


def test_download_files_with_auto_output_succeeds(runner) -> None:
    result = runner.invoke(main, [_URL, "--download-files", "-O"])

    assert result.exit_code == 0, result.output
    assert _FakeSlackDumper.last_instance.download_files is True


def test_plain_dump_without_output_still_works(runner) -> None:
    result = runner.invoke(main, [_URL])

    assert result.exit_code == 0, result.output
    assert _FakeSlackDumper.last_instance.output is None
