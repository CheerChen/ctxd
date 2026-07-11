"""Base dumper abstraction."""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from ctxd.profiling import timed
from ctxd.summary import Summary


@dataclass
class BaseDumper(ABC):
    url: str
    output: str | None
    fmt: str
    quiet: bool = False
    verbose: bool = False
    summary: Summary = field(default_factory=Summary)

    @abstractmethod
    def validate_auth(self) -> None:
        """Validate auth requirements and raise on failure."""

    @abstractmethod
    def fetch(self) -> dict:
        """Fetch source data."""

    @abstractmethod
    def transform(self, raw: dict) -> str:
        """Convert source data to output content."""

    @abstractmethod
    def default_filename(self) -> str:
        """Return a default filename for this source."""

    def render(self) -> str:
        """Fetch + transform and return the rendered content without writing.

        Subclasses override this when they need pre-fetch steps (e.g.
        Confluence short-link resolution).  The base implementation resets
        ``self.summary`` and sets ``source``.
        """
        self.summary = Summary()
        self.validate_auth()
        with timed("stage.fetch"):
            raw = self.fetch()
        with timed("stage.transform"):
            content = self.transform(raw)
        return content

    def dump(self) -> None:
        """Default dump: render → write file or stdout → emit summary.

        Subclasses that need custom export logic (Confluence directory,
        Obsidian) override this.  Overrides are responsible for:
        - resetting ``self.summary`` at the start
        - populating summary counts
        - calling ``self._emit_and_manifest()`` at the end
        """
        content = self.render()
        self.summary.resources_rendered = 1
        self.summary.artifacts_written = 1

        if self.output:
            self._write_text_file(self.output, content)
            self.log(f"✅ Saved to {self.output}")
        else:
            sys.stdout.write(content)

        self._emit_and_manifest()

    def _emit_and_manifest(self, manifest_path: Path | None = None) -> None:
        """Emit the summary to stderr and write a manifest if output is a file.

        *manifest_path* overrides the default manifest location.  When None
        (default), the manifest is derived from ``self.output``.  This is
        used by Obsidian mode where the output path is resolved locally
        but ``self.output`` may still be None (auto-naming with ``-O``).
        """
        self.summary.emit()
        out_path = manifest_path
        if out_path is None and self.output:
            out_path = Path(self.output)
        if out_path is not None:
            manifest = self.summary.write_manifest(out_path)
            self.log(f"📋 Manifest: {manifest}")

    def _write_text_file(self, path: str, content: str) -> None:
        """Write text content to *path* (non-atomic; P1-5 will make it atomic)."""
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    def log(self, message: str) -> None:
        """Progress message — suppressed by ``--quiet``."""
        if not self.quiet:
            print(message, file=sys.stderr)

    def warn(self, message: str) -> None:
        """Warning / diagnostic — **always** printed to stderr, never silenced.

        Data loss paths (fetch failures, skipped pages, dropped attachments,
        truncated results) must use ``warn()`` **and** update ``self.summary``
        so the final summary line is consistent with the warnings.
        """
        print(message, file=sys.stderr)
