"""Base dumper abstraction."""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class BaseDumper(ABC):
    url: str
    output: str | None
    fmt: str
    quiet: bool = False
    verbose: bool = False

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

    def dump(self) -> None:
        self.validate_auth()
        raw = self.fetch()
        content = self.transform(raw)

        if self.output:
            with open(self.output, "w", encoding="utf-8") as handle:
                handle.write(content)
            self.log(f"✅ Saved to {self.output}")
            return

        sys.stdout.write(content)

    def log(self, message: str) -> None:
        if not self.quiet:
            print(message, file=sys.stderr)
