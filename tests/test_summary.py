"""Run diagnostics: the summary line, the manifest, and log vs warn.

Dumper-specific never-silent paths (a failed lookup or download warns and
is counted) are tested next to each dumper; real dump() / CLI runs that
write a manifest are in test_e2e.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ctxd.dumpers.base import BaseDumper
from ctxd.summary import ExportResult, PageStatus, Summary


def test_add_export_result_counts_each_status_and_keeps_notes() -> None:
    s = Summary()
    s.add_export_result(ExportResult(status=PageStatus.WRITTEN, page_id="1", title="A"))
    s.add_export_result(ExportResult(status=PageStatus.SKIPPED, page_id="2", title="B", reason="empty"))
    s.add_export_result(ExportResult(status=PageStatus.FAILED, page_id="3", title="C", reason="err", notes=["note1"]))

    assert (s.resources_rendered, s.skipped, s.failed) == (1, 1, 1)
    assert [i.status for i in s.items] == ["written", "skipped", "failed"]
    assert s.notes == ["note1"]


def test_stderr_line_lists_nonzero_counts_only(capsys: pytest.CaptureFixture) -> None:
    busy = Summary(source="confluence", resources_fetched=5, resources_rendered=3, skipped=1, failed=1, truncated=2)
    quiet = Summary(source="github_pr", resources_fetched=1, resources_rendered=1, artifacts_written=1)

    line = busy.to_stderr_line()
    for part in ("source=confluence", "fetched=5", "rendered=3", "artifacts=0", "skipped=1", "failed=1", "truncated=2"):
        assert part in line
    assert not any(k in quiet.to_stderr_line() for k in ("skipped", "failed", "truncated"))

    busy.emit()
    assert "source=confluence" in capsys.readouterr().err


@pytest.mark.parametrize("target, expected_name", [
    ("pr-1.md", "pr-1.md.manifest.json"),   # file output: manifest beside it
    ("export/", "manifest.json"),           # directory output: manifest inside
])
def test_manifest_placement_and_content(tmp_path: Path, target: str, expected_name: str) -> None:
    out = tmp_path / target
    if target.endswith("/"):
        out.mkdir()
    else:
        out.write_text("content", encoding="utf-8")
    s = Summary(source="confluence", resources_fetched=3)
    s.add_export_result(ExportResult(status=PageStatus.WRITTEN, page_id="1", title="Page 1"))
    s.add_export_result(ExportResult(status=PageStatus.FAILED, page_id="3", title="Page 3", reason="API error"))

    manifest = s.write_manifest(out)

    assert manifest.name == expected_name and manifest.parent == (out if out.is_dir() else out.parent)
    data = json.loads(manifest.read_text())
    assert data["source"] == "confluence" and data["resources_fetched"] == 3
    assert {i["source_id"]: i["reason"] for i in data["items"]} == {"1": "", "3": "API error"}
    assert not list(manifest.parent.glob("*.tmp"))


class _Dumper(BaseDumper):
    def validate_auth(self) -> None: ...
    def fetch(self) -> dict: return {}
    def transform(self, raw: dict) -> str: return ""
    def default_filename(self) -> str: return "x.txt"


@pytest.mark.parametrize("method, quiet, visible", [
    ("log", False, True),
    ("log", True, False),    # progress is silenced by --quiet
    ("warn", False, True),
    ("warn", True, True),    # diagnostics never are
])
def test_quiet_silences_log_but_never_warn(capsys, method: str, quiet: bool, visible: bool) -> None:
    getattr(_Dumper(url="x", output=None, fmt="md", quiet=quiet), method)("message")

    assert ("message" in capsys.readouterr().err) is visible
