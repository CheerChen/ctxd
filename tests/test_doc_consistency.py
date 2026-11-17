"""CLI reference docs, READMEs, and SKILL must not contradict the CLI's defaults.

Each option's default is read from the Click command and rendered into the
phrase its options-table row is expected to carry, so changing a default
fails here until the CLI reference docs say the new value.  The recursion
section check exists because v0.4.3 changed ``--recurse-depth`` from 1 to 0
while the prose still described recursion as on.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from ctxd.cli import main

ROOT = Path(__file__).resolve().parents[1]
DOCS = {
    "en": (ROOT / "docs" / "cli.md").read_text(encoding="utf-8"),
    "cn": (ROOT / "docs" / "cli_cn.md").read_text(encoding="utf-8"),
}
ALL_MARKDOWN = [
    ROOT / "README.md",
    ROOT / "README_CN.md",
    ROOT / "docs" / "auth.md",
    ROOT / "docs" / "auth_cn.md",
    ROOT / "docs" / "cli.md",
    ROOT / "docs" / "cli_cn.md",
]
SKILL = (ROOT / "skills" / "ctxd" / "SKILL.md").read_text(encoding="utf-8")
DEFAULTS = {p.name: p.default for p in main.params if p.name}

_ON_OFF = {"en": {True: "default: on", False: "default: off"}, "cn": {True: "默认开启", False: "默认关闭"}}

# (click param, flag as written in the options table, phrase per language).
# A phrase is a format string taking the CLI default, or None to use the
# on/off wording for a boolean.
OPTIONS = [
    ("fmt", "--format", {"en": "default: `{}`", "cn": "默认 `{}`"}),
    ("diff_mode", "--diff-mode", {"en": "default: `{}`", "cn": "默认 `{}`"}),
    ("max_concurrency", "--max-concurrency", {"en": "default: `{}`", "cn": "默认 `{}`"}),
    ("recurse_depth", "--recurse-depth", {"en": "default: `{}`=off", "cn": "默认 `{}`=关闭"}),
    ("recursive", "--recursive", None),
    ("include_images", "--include-images", None),
    ("clean_body", "--clean-body", None),
    ("no_bots", "--no-bots", {"en": "default: keep all bots", "cn": "默认全部保留"}),
]


def _table_rows(text: str, flag: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("| `") and flag in line.split("|")[1]]


@pytest.mark.parametrize("lang", ["en", "cn"])
@pytest.mark.parametrize("param, flag, phrases", OPTIONS, ids=[o[0] for o in OPTIONS])
def test_options_table_states_the_cli_default(param: str, flag: str, phrases, lang: str) -> None:
    default = DEFAULTS[param]
    expected = _ON_OFF[lang][default] if phrases is None else phrases[lang].format(default)
    rows = _table_rows(DOCS[lang], flag)

    assert rows, f"no options-table row for {flag} in CLI reference ({lang})"
    for row in rows:
        assert expected in row, f"{flag} default is {default!r}; row says: {row}"


@pytest.mark.parametrize("lang, heading, default_off, stale", [
    ("en", "Cross-source recursion", r"off by default|by default.{0,40}off", ["By default, `ctxd` scans", "Default: depth=1"]),
    ("cn", "跨源递归", r"默认.{0,20}关闭", ["默认情况下，`ctxd` 会扫描", "默认 depth=1"]),
])
def test_recursion_section_says_off_by_default(lang, heading, default_off, stale) -> None:
    assert DEFAULTS["recurse_depth"] == 0, "recursion became default-on: rewrite this section check"
    match = re.search(rf"^##\s+{re.escape(heading)}\s*$(.*?)(?=^##\s|\Z)", DOCS[lang], re.M | re.S)

    assert match, f"section {heading!r} not found"
    section = match.group(1)
    assert re.search(default_off, section, re.IGNORECASE), "no explicit default-off statement"
    for phrase in stale:
        assert phrase not in section


def test_skill_says_recursion_is_off_by_default() -> None:
    assert "off by default" in SKILL
    assert "recursion is on by default" not in SKILL


def test_help_renders() -> None:
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "Usage:" in result.output


@pytest.mark.parametrize("md_path", ALL_MARKDOWN, ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_markdown_links_resolve(md_path: Path) -> None:
    text = md_path.read_text(encoding="utf-8")
    for raw_target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
        if raw_target.startswith(("http://", "https://", "#")):
            continue
        rel_file = raw_target.split("#", 1)[0]
        target = (md_path.parent / rel_file).resolve()
        assert target.exists(), f"{md_path.relative_to(ROOT)} links to missing path {raw_target!r}"
