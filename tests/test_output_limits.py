"""Output limits: --max-chars truncation, atomic writes, download size budgets."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from conftest import install_fake_github
from ctxd.cli import main
from ctxd.download_limits import DownloadLimitExceeded, RunBudget
from ctxd.dumpers.base import _apply_stdout_limit, _atomic_write_bytes, _atomic_write_text
from ctxd.summary import Summary

_SLACK_URL = "https://example.slack.com/archives/C123/p1234567890123456"


def _body(result: str) -> str:
    """Truncated content without the trailing notice."""
    idx = result.find("\n\n> [ctxd:")
    return result[:idx] if idx > 0 else result


# ---------------------------------------------------------------------------
# --max-chars truncation
# ---------------------------------------------------------------------------

def test_content_within_limit_is_untouched() -> None:
    summary = Summary(source="test")

    assert _apply_stdout_limit("short\n", max_chars=100, summary=summary) == "short\n"
    assert summary.truncated == 0 and not summary.notes


def test_negative_limit_disables_truncation() -> None:
    assert _apply_stdout_limit("x" * 500, max_chars=-1) == "x" * 500


def test_zero_limit_uses_the_default(monkeypatch) -> None:
    monkeypatch.setattr("ctxd.dumpers.base._DEFAULT_STDOUT_MAX_CHARS", 200)

    result = _apply_stdout_limit("line\n" * 100, max_chars=0)

    assert len(result) <= 200 and "exceeded 200 characters" in result


@pytest.mark.parametrize("limit, marker", [
    (1, "…"),                       # nothing fits: the marker alone
    (10, "…"),                      # ultra-short notice does not fit either
    (15, "[ctxd…]"),                # ultra-short notice
    (30, "[ctxd: truncated]"),      # short notice
    (50, "[ctxd: truncated]"),
    (150, "Original size: 2000"),   # full notice with sizes
    (500, "Original size: 2000"),
])
def test_output_never_exceeds_limit_and_says_it_was_cut(limit: int, marker: str) -> None:
    result = _apply_stdout_limit("A" * 1999 + "\n", max_chars=limit)

    assert len(result) <= limit
    assert marker in result
    if limit == 1:
        assert result == "…"  # not the first character of the content


def test_cut_lands_on_a_line_boundary() -> None:
    content = "".join(f"line {i:04d}\n" for i in range(500))

    body = _body(_apply_stdout_limit(content, max_chars=1000))

    assert body and content.startswith(body + "\n")


@pytest.mark.parametrize("content, limit", [
    ("```python\n" + "x = 1\n" * 200, 500),                                       # fence opens early
    ("header\n" + "normal line\n" * 8000 + "```python\n" + "code\n" * 2000, 100000),  # fence opens late
])
def test_open_code_fence_is_closed(content: str, limit: int) -> None:
    result = _apply_stdout_limit(content, max_chars=limit)

    assert len(result) <= limit
    assert _body(result).count("```") % 2 == 0


@pytest.mark.parametrize("channel", ["stdout", "file"])
def test_truncation_is_recorded_in_the_summary(channel: str) -> None:
    summary = Summary(source="test")

    result = _apply_stdout_limit("x" * 2000, max_chars=500, summary=summary, channel=channel)

    assert summary.truncated == 1
    assert summary.notes == [f"{channel} truncated: 2000 → {len(result)} chars (limit: 500)"]


@pytest.mark.parametrize("max_chars, truncated", [("500", True), ("-1", False)])
def test_cli_max_chars_applies_to_file_output(tmp_path: Path, monkeypatch, max_chars: str, truncated: bool) -> None:
    install_fake_github(monkeypatch, pull={"title": "T", "body": "A" * 10000},
                        diff="diff --git a/f b/f\n+line\n" * 200)
    out_file = tmp_path / "out.md"

    result = CliRunner().invoke(main, [
        "https://github.com/o/r/pull/1", "-o", str(out_file), "--max-chars", max_chars,
        "--max-file-size", "10485760", "--max-run-size", "104857600",
    ])

    assert result.exit_code == 0, f"{result.output}\n{result.exception}"
    content = out_file.read_text()
    manifest = json.loads((tmp_path / "out.md.manifest.json").read_text())
    if truncated:
        assert len(content) <= 500 and "Original size:" in content
        assert manifest["truncated"] == 1
    else:
        assert "A" * 10000 in content
        assert manifest.get("truncated", 0) == 0


def test_confluence_tree_truncates_every_page_and_counts_them(tmp_path: Path, monkeypatch) -> None:
    from ctxd.dumpers.confluence import ConfluenceDumper

    d = ConfluenceDumper(
        url="https://test.atlassian.net/wiki/spaces/ABC/pages/100/Root",
        output=str(tmp_path / "export"), fmt="md", recursive=True, max_chars=300,
    )
    monkeypatch.setattr(d, "validate_auth", lambda: None)
    monkeypatch.setattr(d, "_resolve_short_link", lambda: None)
    d.client = MagicMock()
    d.client.base_url = "https://test.atlassian.net"
    body = {"storage": {"value": f"<p>{'X' * 500}</p>"}}
    d.client.get_page = MagicMock(return_value={"id": "100", "title": "Root", "body": body})
    d.client.get_descendants = MagicMock(return_value=[
        {"id": str(200 + i), "title": f"Page{i}", "body": body} for i in range(3)
    ])
    for name in ("get_inline_comments", "get_footer_comments", "get_attachments"):
        setattr(d.client, name, MagicMock(return_value=[]))
    d.client.get_space_name = MagicMock(return_value="SPACE")
    d.client.get_user_display_name = MagicMock(return_value="Author")

    d.dump()

    for page_dir in ("100_Root", *(f"{200 + i}_Page{i}" for i in range(3))):
        content = (tmp_path / "export" / page_dir / "README.md").read_text()
        assert len(content) <= 300 and "truncated" in content
    manifest = json.loads((tmp_path / "export" / "manifest.json").read_text())
    assert manifest["truncated"] == 4


# ---------------------------------------------------------------------------
# Atomic writes
# ---------------------------------------------------------------------------

def test_atomic_write_creates_parents_and_leaves_no_temp(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "dir" / "output.md"

    _atomic_write_text(path, "nested")

    assert path.read_text() == "nested"
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize("write, original, new", [
    (_atomic_write_text, "original", "replacement"),
    (_atomic_write_bytes, b"original", b"replacement"),
])
def test_failed_write_keeps_the_existing_file(tmp_path: Path, monkeypatch, write, original, new) -> None:
    path = tmp_path / "out"
    write(path, original)

    def failing_replace(src, dst):
        raise OSError("simulated rename failure")

    monkeypatch.setattr("ctxd.dumpers.base.os.replace", failing_replace)
    with pytest.raises(OSError):
        write(path, new)

    assert (path.read_text() if isinstance(original, str) else path.read_bytes()) == original
    assert list(tmp_path.iterdir()) == [path]


# ---------------------------------------------------------------------------
# Download budgets (--max-file-size / --max-run-size)
# ---------------------------------------------------------------------------

def test_run_budget_raises_once_exhausted() -> None:
    budget = RunBudget(max_run_bytes=1000)
    budget.check_and_reserve(400)
    budget.check_and_reserve(500)
    assert budget.used == 900

    with pytest.raises(DownloadLimitExceeded):
        budget.check_and_reserve(500)


def test_run_budget_is_thread_safe() -> None:
    budget = RunBudget(max_run_bytes=100000)

    def worker() -> None:
        for _ in range(100):
            budget.check_and_reserve(1)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert budget.used == 1000


def _slack_downloader(tmp_path: Path, monkeypatch, responses: list[tuple[dict, list[bytes]]], **limits):
    """A SlackDumper whose file downloads return *responses* in order."""
    from ctxd.dumpers.slack import SlackDumper

    dumper = SlackDumper(url=_SLACK_URL, output=str(tmp_path / "out.md"), fmt="md",
                         download_files=True, **limits)
    monkeypatch.setattr(dumper, "token", "xoxb-test")
    closed: list[bool] = []
    queue = list(responses)

    class FakeResp:
        def __init__(self, headers, chunks):
            self.headers = {"content-type": "image/png", **headers}
            self._chunks = chunks

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size=8192):
            yield from self._chunks

        def close(self):
            closed.append(True)

    monkeypatch.setattr(dumper.session, "get", lambda url, **kw: FakeResp(*queue.pop(0)))
    return dumper, closed


def _file(fid: str) -> list[dict]:
    return [{"id": fid, "name": f"{fid}.png", "url_private_download": f"https://slack.com/files/{fid}/dl"}]


def test_negative_limits_mean_unlimited(tmp_path: Path, monkeypatch) -> None:
    dumper, _ = _slack_downloader(tmp_path, monkeypatch, [
        ({"content-length": "1000"}, [b"\x00" * 1000]),
        ({"content-length": "2000"}, [b"\x00" * 2000]),
    ], max_file_size=-1, max_run_size=-1)

    dumper._download_files(_file("F1"), tmp_path)
    dumper._download_files(_file("F2"), tmp_path)

    assert (tmp_path / "attachments" / "IMG_F1.png").stat().st_size == 1000
    assert (tmp_path / "attachments" / "IMG_F2.png").stat().st_size == 2000


def test_run_budget_carries_across_download_calls(tmp_path: Path, monkeypatch) -> None:
    dumper, _ = _slack_downloader(tmp_path, monkeypatch, [
        ({"content-length": "1000"}, [b"\x00" * 1000]),
        ({"content-length": "1000"}, [b"\x00" * 1000]),
    ], max_file_size=1000, max_run_size=1500)

    dumper._download_files(_file("F1"), tmp_path)
    dumper._download_files(_file("F2"), tmp_path)

    assert (tmp_path / "attachments" / "IMG_F1.png").exists()
    assert not (tmp_path / "attachments" / "IMG_F2.png").exists()
    assert dumper.summary.skipped >= 1


@pytest.mark.parametrize("headers, chunks", [
    ({"content-length": "1000"}, [b"\x00" * 1000]),   # rejected up front by Content-Length
    ({}, [b"\x00" * 80, b"\x00" * 80]),                # rejected mid-stream
])
def test_oversized_file_is_rejected_and_response_closed(tmp_path: Path, monkeypatch, headers, chunks) -> None:
    dumper, closed = _slack_downloader(tmp_path, monkeypatch, [(headers, chunks)], max_file_size=100)

    dumper._download_files(_file("F1"), tmp_path)

    assert closed
    assert not (tmp_path / "attachments" / "IMG_F1.png").exists()
    assert dumper.summary.skipped >= 1
    assert any("size limit" in n for n in dumper.summary.notes)


def test_recursion_children_share_the_parents_budget(monkeypatch) -> None:
    import ctxd.recurse as recurse_mod
    from ctxd.dumpers.slack import SlackDumper

    parent = SlackDumper(url=_SLACK_URL, output=None, fmt="md", download_files=True, max_run_size=100)
    children: list = []
    original_build = recurse_mod._build_dumper

    def capturing_build(url, opts):
        child = original_build(url, opts)
        child.render = lambda: "child content"
        children.append(child)
        return child

    monkeypatch.setattr(recurse_mod, "_build_dumper", capturing_build)
    monkeypatch.setattr(parent, "validate_auth", lambda: None)
    monkeypatch.setattr(parent, "render", lambda: (
        "https://example.slack.com/archives/C456/p1111111111111111\n"
        "https://example.slack.com/archives/C789/p2222222222222222"
    ))

    recurse_mod.render_with_recurse(parent, depth=1)

    assert len(children) == 2
    assert all(child.run_budget is parent.run_budget for child in children)
