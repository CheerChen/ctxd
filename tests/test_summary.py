"""Tests for Summary dataclass behavior and recurse summary tracking.

Low-value tests (enum string values, isinstance, defaults-are-zero) have
been removed.  Manifest and Confluence page-status integration tests live
in ``test_summary_integration.py``.
"""

from __future__ import annotations

import pytest

from ctxd.summary import ExportResult, ItemRecord, PageStatus, Summary


# ---------------------------------------------------------------------------
# Summary dataclass — behavior tests with real logic
# ---------------------------------------------------------------------------

class TestSummaryDataclass:
    def test_merge_combines_counts_and_notes(self) -> None:
        a = Summary(resources_fetched=5, resources_rendered=3, failed=2)
        b = Summary(resources_fetched=10, resources_rendered=7, skipped=1, notes=["x"])
        a.merge(b)
        assert a.resources_fetched == 15
        assert a.resources_rendered == 10
        assert a.skipped == 1
        assert a.failed == 2
        assert a.notes == ["x"]

    def test_merge_combines_items(self) -> None:
        a = Summary()
        a.add_item(source_id="1", status="written", title="A")
        b = Summary()
        b.add_item(source_id="2", status="failed", title="B", reason="err")
        a.merge(b)
        assert len(a.items) == 2
        assert a.resources_rendered == 1
        assert a.failed == 1

    def test_add_item_increments_counter(self) -> None:
        s = Summary()
        s.add_item(source_id="1", status="written", title="A")
        s.add_item(source_id="2", status="skipped", title="B", reason="empty")
        s.add_item(source_id="3", status="failed", title="C", reason="err")
        assert s.resources_rendered == 1
        assert s.skipped == 1
        assert s.failed == 1
        assert len(s.items) == 3

    def test_add_export_result_aggregates(self) -> None:
        s = Summary()
        s.add_export_result(ExportResult(status=PageStatus.WRITTEN, page_id="1", title="A"))
        s.add_export_result(ExportResult(status=PageStatus.SKIPPED, page_id="2", title="B", reason="empty"))
        s.add_export_result(ExportResult(status=PageStatus.FAILED, page_id="3", title="C", reason="err", notes=["note1"]))
        assert s.resources_rendered == 1
        assert s.skipped == 1
        assert s.failed == 1
        assert len(s.items) == 3
        assert "note1" in s.notes

    def test_total(self) -> None:
        s = Summary(resources_rendered=3, skipped=2, failed=1)
        assert s.total == 6

    def test_to_dict_roundtrip(self) -> None:
        s = Summary(source="confluence", resources_fetched=5, resources_rendered=3, skipped=1, failed=1)
        s.add_item(source_id="1", status="written", title="A")
        d = s.to_dict()
        assert d["source"] == "confluence"
        assert d["resources_fetched"] == 5
        assert len(d["items"]) == 1
        assert d["items"][0]["source_id"] == "1"

    def test_to_stderr_line_includes_nonzero_counts(self) -> None:
        s = Summary(source="confluence", resources_fetched=5, resources_rendered=3, skipped=1, failed=1, truncated=2)
        line = s.to_stderr_line()
        assert "source=confluence" in line
        assert "fetched=5" in line
        assert "rendered=3" in line
        assert "artifacts=0" in line
        assert "skipped=1" in line
        assert "failed=1" in line
        assert "truncated=2" in line

    def test_to_stderr_line_omits_zero_counts(self) -> None:
        s = Summary(source="github_pr", resources_fetched=1, resources_rendered=1, artifacts_written=1)
        line = s.to_stderr_line()
        assert "skipped" not in line
        assert "failed" not in line
        assert "truncated" not in line

    def test_emit_prints_to_stderr(self, capsys: pytest.CaptureFixture) -> None:
        s = Summary(source="slack_thread", resources_fetched=10, resources_rendered=1)
        s.emit()
        captured = capsys.readouterr()
        assert "source=slack_thread" in captured.err
        assert "fetched=10" in captured.err


# ---------------------------------------------------------------------------
# Recurse summary tracking
# ---------------------------------------------------------------------------

class TestRecurseSummary:
    def test_truncated_count_in_summary(self, monkeypatch) -> None:
        from ctxd.recurse import MAX_CHILDREN_PER_LEVEL, render_with_recurse

        parent_url = "https://app.slack.com/client/T/C/thread/C-123.456"
        child_urls = [
            f"https://site.atlassian.net/browse/PROJ-{i}"
            for i in range(MAX_CHILDREN_PER_LEVEL + 3)
        ]
        parent_content = "See " + " ".join(child_urls) + "\n"

        class FakeDumper:
            def __init__(self, url, content="content\n", fail=None):
                self.url = url
                self.output = None
                self.fmt = "md"
                self.quiet = True
                self.verbose = False
                self.summary = Summary()
                self._content = content
                self._fail = fail

            def render(self):
                if self._fail:
                    raise self._fail
                return self._content

            def log(self, msg): pass

        dumper = FakeDumper(url=parent_url, content=parent_content)

        def factory(url, opts):
            return FakeDumper(url=url, content=f"content {url}\n")

        monkeypatch.setattr("ctxd.recurse._build_dumper", factory)
        render_with_recurse(dumper, depth=1)

        assert dumper.summary.truncated == 3
        # 1 (primary) + MAX_CHILDREN_PER_LEVEL (children) fetched/rendered
        assert dumper.summary.resources_rendered == 1 + MAX_CHILDREN_PER_LEVEL
        assert dumper.summary.resources_fetched == 1 + MAX_CHILDREN_PER_LEVEL
        # Recursion embeds all content into one artifact.
        assert dumper.summary.artifacts_written == 0  # CLI sets it to 1

    def test_failed_child_in_summary(self, monkeypatch) -> None:
        from ctxd.recurse import render_with_recurse

        parent_url = "https://app.slack.com/client/T/C/thread/C-123.456"
        child_url = "https://site.atlassian.net/browse/PROJ-1"
        parent_content = f"See {child_url}\n"

        class FakeDumper:
            def __init__(self, url, content="content\n", fail=None):
                self.url = url
                self.output = None
                self.fmt = "md"
                self.quiet = True
                self.verbose = False
                self.summary = Summary()
                self._content = content
                self._fail = fail

            def render(self):
                if self._fail:
                    raise self._fail
                return self._content

            def log(self, msg): pass

        dumper = FakeDumper(url=parent_url, content=parent_content)

        def factory(url, opts):
            return FakeDumper(url=url, fail=RuntimeError("boom"))

        monkeypatch.setattr("ctxd.recurse._build_dumper", factory)
        render_with_recurse(dumper, depth=1)

        assert dumper.summary.failed == 1
        # Primary resource still counts as rendered even if child failed.
        assert dumper.summary.resources_rendered == 1
        assert any("boom" in note for note in dumper.summary.notes)
