"""Completeness summary for ctxd runs.

Tracks counts and structured per-item records so the user or agent can
judge whether the output is complete, even with ``--quiet``.

Field semantics (consistent across all sources):

- ``resources_fetched``: number of **source resources** retrieved from APIs.
    For single-item sources (GitHub PR, Slack thread, Jira issue) this is 1.
    For Confluence recursive export this is the number of pages discovered.
    Recursively expanded child URLs each count as 1.
- ``resources_rendered``: number of source resources successfully rendered
    into content (a subset of fetched; excludes skipped/failed).
- ``artifacts_written``: number of **output artifacts** written to disk or
    stdout.  1 for stdout or a single file.  N for Confluence recursive
    directory export (one per page directory).  Recursion does NOT increase
    this — all child content is embedded into the same artifact.
- ``skipped``: items intentionally excluded (empty pages, missing credentials).
- ``failed``: items that encountered an error and could not be fetched or written.
- ``truncated``: URLs or content dropped due to caps (e.g. recursion cap).
- ``items``: structured per-item records with ``source_id``, ``status``,
    ``title``, and ``reason`` — sufficient to locate and re-fetch failed items.
- ``notes``: free-form diagnostic strings (e.g. "3 user lookups failed").

For directory exports (Confluence recursive), a ``manifest.json`` is written
alongside the page tree with the full breakdown.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class PageStatus(str, Enum):
    """Outcome of processing a single resource."""

    WRITTEN = "written"
    SKIPPED = "skipped"   # empty page, intentionally excluded
    FAILED = "failed"     # exception during fetch or transform


@dataclass
class ItemRecord:
    """Structured record for a single resource in the summary."""

    source_id: str = ""
    status: str = ""       # PageStatus value
    title: str = ""
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "status": self.status,
            "title": self.title,
            "reason": self.reason,
        }


@dataclass
class ExportResult:
    """Thread-safe result returned by per-page export workers.

    Workers produce this object instead of directly mutating ``Summary``,
    so the main thread can aggregate results without lock contention.
    """

    status: PageStatus
    page_id: str = ""
    title: str = ""
    reason: str = ""
    notes: list[str] = field(default_factory=list)

    def to_item(self) -> ItemRecord:
        return ItemRecord(
            source_id=self.page_id,
            status=self.status.value,
            title=self.title,
            reason=self.reason,
        )


@dataclass
class Summary:
    """Accumulated counts for a single ctxd run."""

    source: str = ""
    resources_fetched: int = 0
    resources_rendered: int = 0
    artifacts_written: int = 0
    skipped: int = 0
    failed: int = 0
    truncated: int = 0
    notes: list[str] = field(default_factory=list)
    items: list[ItemRecord] = field(default_factory=list)

    def merge(self, other: Summary) -> None:
        """Merge another summary into this one (in-place)."""
        self.resources_fetched += other.resources_fetched
        self.resources_rendered += other.resources_rendered
        self.artifacts_written += other.artifacts_written
        self.skipped += other.skipped
        self.failed += other.failed
        self.truncated += other.truncated
        self.notes.extend(other.notes)
        self.items.extend(other.items)

    def add_note(self, note: str) -> None:
        self.notes.append(note)

    def add_item(
        self,
        source_id: str = "",
        status: str = "",
        title: str = "",
        reason: str = "",
    ) -> None:
        """Record a structured item. Also increments the matching counter."""
        self.items.append(ItemRecord(source_id=source_id, status=status, title=title, reason=reason))
        if status == PageStatus.WRITTEN.value:
            self.resources_rendered += 1
        elif status == PageStatus.SKIPPED.value:
            self.skipped += 1
        elif status == PageStatus.FAILED.value:
            self.failed += 1

    def add_export_result(self, result: ExportResult) -> None:
        """Aggregate an ``ExportResult`` (from a worker) into this summary.

        Thread-safe to call from the main thread after all workers finish.
        """
        self.items.append(result.to_item())
        if result.status is PageStatus.WRITTEN:
            self.resources_rendered += 1
        elif result.status is PageStatus.SKIPPED:
            self.skipped += 1
        elif result.status is PageStatus.FAILED:
            self.failed += 1
        self.notes.extend(result.notes)

    @property
    def total(self) -> int:
        return self.resources_rendered + self.skipped + self.failed

    def to_stderr_line(self) -> str:
        """One-line summary suitable for stderr."""
        parts = [f"ctxd summary: source={self.source or 'unknown'}"]
        parts.append(f"fetched={self.resources_fetched}")
        parts.append(f"rendered={self.resources_rendered}")
        parts.append(f"artifacts={self.artifacts_written}")
        if self.skipped:
            parts.append(f"skipped={self.skipped}")
        if self.failed:
            parts.append(f"failed={self.failed}")
        if self.truncated:
            parts.append(f"truncated={self.truncated}")
        line = " | ".join(parts)
        if self.notes:
            line += "\n  notes: " + "; ".join(self.notes)
        return line

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "resources_fetched": self.resources_fetched,
            "resources_rendered": self.resources_rendered,
            "artifacts_written": self.artifacts_written,
            "skipped": self.skipped,
            "failed": self.failed,
            "truncated": self.truncated,
            "notes": list(self.notes),
            "items": [item.to_dict() for item in self.items],
        }

    def emit(self) -> None:
        """Print the summary to stderr (always visible, never silenced)."""
        print(self.to_stderr_line(), file=sys.stderr)

    def write_manifest(self, path: Path) -> Path:
        """Write a ``manifest.json`` at *path*.

        If *path* is a directory, the file is placed inside as
        ``manifest.json``.  If *path* is a file path, it is used directly
        (e.g. ``output.md.manifest.json``).
        Returns the path to the written manifest.
        """
        if path.is_dir():
            manifest_path = path / "manifest.json"
        else:
            manifest_path = path.with_suffix(path.suffix + ".manifest.json")
        manifest_path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return manifest_path
