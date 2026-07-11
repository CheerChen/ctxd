"""Verify that README / SKILL documentation stays consistent with CLI defaults.

This test extracts default values from the Click command parameters and
checks that the documentation files do not contradict them.  It catches the
class of drift that happened in v0.4.3 when ``--recurse-depth`` default
changed from 1 to 0 but the prose in the Cross-source recursion section was
not updated.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from ctxd.cli import main

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
README_CN = ROOT / "README_CN.md"
SKILL = ROOT / "skills" / "ctxd" / "SKILL.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cli_defaults() -> dict[str, object]:
    """Return ``{param_name: default}`` for every option on the CLI."""
    defaults: dict[str, object] = {}
    for param in main.params:
        name = param.name
        if name is None:
            continue
        defaults[name] = param.default
    return defaults


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def defaults() -> dict[str, object]:
    return _cli_defaults()


@pytest.fixture(scope="module")
def readme_text() -> str:
    return _read(README)


@pytest.fixture(scope="module")
def readme_cn_text() -> str:
    return _read(README_CN)


@pytest.fixture(scope="module")
def skill_text() -> str:
    return _read(SKILL)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRecurseDepthDefault:
    """``--recurse-depth`` default is 0 (off). Docs must state this explicitly."""

    @pytest.fixture
    def expected(self, defaults: dict[str, object]) -> int:
        return int(defaults["recurse_depth"])  # type: ignore[arg-type]

    def test_default_is_off(self, expected: int) -> None:
        assert expected == 0, "if this changes, update the tests below too"

    def test_readme_states_off_by_default(self, readme_text: str) -> None:
        """The Cross-source recursion section must contain an explicit
        default-off statement — not merely the word 'off' somewhere.

        Accepts either ``off by default`` or ``by default ... off`` (within
        the same sentence), but rejects text that only contains ``off`` in
        an unrelated context (e.g. ``--no-recurse to turn it off``).
        """
        recursion_section = _extract_section(readme_text, "Cross-source recursion")
        assert recursion_section, "Section 'Cross-source recursion' not found"
        # Must contain an explicit default-off declaration.
        has_off_by_default = bool(re.search(r"off by default", recursion_section, re.IGNORECASE))
        has_by_default_off = bool(re.search(r"by default.{0,40}off", recursion_section, re.IGNORECASE))
        assert has_off_by_default or has_by_default_off, (
            "Missing explicit default-off statement in recursion section"
        )
        # Must not contain the old prose that implied recursion was on.
        assert "By default, `ctxd` scans" not in recursion_section

    def test_readme_no_depth_1_default(self, readme_text: str) -> None:
        recursion_section = _extract_section(readme_text, "Cross-source recursion")
        # The old comment said "# Default: depth=1" — that was wrong.
        assert "Default: depth=1" not in recursion_section

    def test_readme_cn_states_off_by_default(self, readme_cn_text: str) -> None:
        """中文文档的跨源递归章节必须包含明确的默认关闭声明。

        接受「默认关闭」或「默认...关闭」句式，但拒绝仅在无关上下文
        出现「关闭」的文档（如「--no-recurse 关闭」）。
        """
        recursion_section = _extract_section(readme_cn_text, "跨源递归")
        assert recursion_section, "Section '跨源递归' not found"
        has_default_off = "默认关闭" in recursion_section
        has_default_context_off = bool(re.search(r"默认.{0,20}关闭", recursion_section))
        assert has_default_off or has_default_context_off, (
            "Missing explicit default-off statement in recursion section"
        )
        assert "默认情况下，`ctxd` 会扫描" not in recursion_section

    def test_readme_cn_no_depth_1_default(self, readme_cn_text: str) -> None:
        recursion_section = _extract_section(readme_cn_text, "跨源递归")
        assert "默认 depth=1" not in recursion_section

    def test_skill_states_off_by_default(self, skill_text: str) -> None:
        assert "recursion is on by default" not in skill_text
        assert "off by default" in skill_text

    def test_readme_global_options_table(self, readme_text: str) -> None:
        # The Global Options table should say default 0=off
        assert "default: `0`=off" in readme_text or "default: 0=off" in readme_text

    def test_readme_cn_global_options_table(self, readme_cn_text: str) -> None:
        assert "默认 `0`=关闭" in readme_cn_text or "默认 0=关闭" in readme_cn_text


class TestConfluenceRecursiveDefault:
    """``--recursive`` default is False (off)."""

    def test_default_is_off(self, defaults: dict[str, object]) -> None:
        assert defaults["recursive"] is False

    def test_readme_says_off(self, readme_text: str) -> None:
        # In the Confluence options table
        assert "Include child pages (default: off)" in readme_text

    def test_readme_cn_says_off(self, readme_cn_text: str) -> None:
        assert "包含子页面（默认关闭）" in readme_cn_text


class TestIncludeImagesDefault:
    """``--include-images`` default is False (off)."""

    def test_default_is_off(self, defaults: dict[str, object]) -> None:
        assert defaults["include_images"] is False

    def test_readme_says_off(self, readme_text: str) -> None:
        assert "Download referenced images (default: off)" in readme_text

    def test_readme_cn_says_off(self, readme_cn_text: str) -> None:
        assert "下载正文引用的图片（默认关闭）" in readme_cn_text


class TestFormatDefault:
    """``--format`` default is ``md``."""

    def test_default_is_md(self, defaults: dict[str, object]) -> None:
        assert defaults["fmt"] == "md"

    def test_readme_says_md(self, readme_text: str) -> None:
        assert "default: `md`" in readme_text or "default: md" in readme_text

    def test_readme_cn_says_md(self, readme_cn_text: str) -> None:
        assert "默认 `md`" in readme_cn_text


class TestDiffModeDefault:
    """``--diff-mode`` default is ``compact``."""

    def test_default_is_compact(self, defaults: dict[str, object]) -> None:
        assert defaults["diff_mode"] == "compact"

    def test_readme_says_compact(self, readme_text: str) -> None:
        assert "default: `compact`" in readme_text or "default: compact" in readme_text

    def test_readme_cn_says_compact(self, readme_cn_text: str) -> None:
        assert "默认 `compact`" in readme_cn_text


class TestMaxConcurrencyDefault:
    """``--max-concurrency`` default is 5."""

    def test_default_is_5(self, defaults: dict[str, object]) -> None:
        assert defaults["max_concurrency"] == 5

    def test_readme_says_5(self, readme_text: str) -> None:
        assert "default: `5`" in readme_text or "default: 5" in readme_text

    def test_readme_cn_says_5(self, readme_cn_text: str) -> None:
        assert "默认 `5`" in readme_cn_text


class TestCleanBodyDefault:
    """``--clean-body`` default is True (on)."""

    def test_default_is_on(self, defaults: dict[str, object]) -> None:
        assert defaults["clean_body"] is True

    def test_readme_says_on(self, readme_text: str) -> None:
        assert "default: on" in readme_text

    def test_readme_cn_says_on(self, readme_cn_text: str) -> None:
        assert "默认开启" in readme_cn_text


class TestNoBotsDefault:
    """``--no-bots`` default is False (bots kept by default)."""

    def test_default_is_false(self, defaults: dict[str, object]) -> None:
        assert defaults["no_bots"] is False

    def test_readme_says_keep(self, readme_text: str) -> None:
        assert "default: keep all bots" in readme_text

    def test_readme_cn_says_keep(self, readme_cn_text: str) -> None:
        assert "默认全部保留" in readme_cn_text


class TestCliHelpMatchesParams:
    """``ctxd --help`` output should list every option without error."""

    def test_help_exits_zero(self) -> None:
        result = CliRunner().invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _extract_section(text: str, heading: str) -> str:
    """Return the text between *heading* and the next same-level heading."""
    pattern = rf"^##\s+{re.escape(heading)}\s*$"
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        return ""
    start = match.end()
    # Find the next ## heading (or end of file)
    next_heading = re.search(r"^##\s+", text[start:], re.MULTILINE)
    if next_heading:
        return text[start : start + next_heading.start()]
    return text[start:]
