from __future__ import annotations

from collections import OrderedDict

from ctxd.dumpers.github_pr import GitHubPRDumper


def _make_dumper(no_bots: bool = False) -> GitHubPRDumper:
    return GitHubPRDumper(
        url="https://github.com/o/r/pull/1",
        output=None,
        fmt="md",
        no_bots=no_bots,
    )


def _make_raw(**overrides) -> dict:
    base = {
        "number": "1",
        "title": "t",
        "body": "b",
        "timeline_comments": [],
        "diff_comments": OrderedDict(),
        "reviews": [],
        "diff_content": "",
    }
    base.update(overrides)
    return base


def test_sections_ordered_reviews_inline_timeline() -> None:
    dumper = _make_dumper()
    raw = _make_raw(
        reviews=[{
            "login": "alice", "is_bot": False, "state": "APPROVED",
            "body": "", "submitted_at": "2026-04-20T01:00:00Z",
        }],
        diff_comments=OrderedDict([
            ("foo.go", [{
                "login": "devin-ai-integration", "is_bot": True,
                "body": "finding", "line": 35, "start_line": 34,
                "side": "LEFT", "created_at": "2026-04-20T02:00:00Z",
                "in_reply_to_id": None,
            }])
        ]),
        timeline_comments=[{
            "login": "bob", "is_bot": False, "body": "go vet!",
            "created_at": "2026-04-20T03:00:00Z",
        }],
    )
    out = dumper.transform(raw)
    r_idx = out.index("## Reviews")
    i_idx = out.index("## Inline Review Comments")
    t_idx = out.index("## Timeline Comments")
    assert r_idx < i_idx < t_idx


def test_empty_body_approval_is_rendered_with_state() -> None:
    dumper = _make_dumper()
    raw = _make_raw(reviews=[{
        "login": "alice", "is_bot": False, "state": "APPROVED",
        "body": "", "submitted_at": "2026-04-20T01:00:00Z",
    }])
    out = dumper.transform(raw)
    assert "@alice" in out
    assert "**APPROVED**" in out
    assert "(2026-04-20T01:00:00Z)" in out


def test_inline_comment_shows_side_and_range_and_bot_tag() -> None:
    dumper = _make_dumper()
    raw = _make_raw(diff_comments=OrderedDict([
        ("cmd/exec/show_test.go", [{
            "login": "devin-ai-integration", "is_bot": True,
            "body": "Removed failing test masks bug",
            "line": 35, "start_line": 34, "side": "LEFT",
            "created_at": "2026-04-20T02:00:00Z", "in_reply_to_id": None,
        }])
    ]))
    out = dumper.transform(raw)
    assert "### `cmd/exec/show_test.go`" in out
    assert "@devin-ai-integration[bot]" in out
    assert "[LEFT]" in out
    assert "L34-35" in out
    assert "Removed failing test masks bug" in out


def test_inline_comment_single_line_when_no_range() -> None:
    dumper = _make_dumper()
    raw = _make_raw(diff_comments=OrderedDict([
        ("f.py", [{
            "login": "a", "is_bot": False, "body": "x",
            "line": 10, "start_line": None, "side": "RIGHT",
            "created_at": "", "in_reply_to_id": None,
        }])
    ]))
    out = dumper.transform(raw)
    assert "L10" in out
    assert "L10-10" not in out


def test_author_tag_does_not_double_suffix_bot() -> None:
    dumper = _make_dumper()
    raw = _make_raw(timeline_comments=[{
        "login": "github-actions[bot]", "is_bot": True, "body": "hi",
        "created_at": "2026-04-20T03:00:00Z",
    }])
    out = dumper.transform(raw)
    assert "@github-actions[bot]" in out
    assert "[bot][bot]" not in out


def test_is_bot_filter_opt_in() -> None:
    dumper_default = GitHubPRDumper(url="https://github.com/o/r/pull/1", output=None, fmt="md")
    dumper_filter = GitHubPRDumper(url="https://github.com/o/r/pull/1", output=None, fmt="md", no_bots=True)
    assert dumper_default.no_bots is False
    assert dumper_filter.no_bots is True


def test_timeline_comment_timestamp_rendered() -> None:
    dumper = _make_dumper()
    raw = _make_raw(timeline_comments=[{
        "login": "bob", "is_bot": False, "body": "thanks",
        "created_at": "2026-04-20T03:00:00Z",
    }])
    out = dumper.transform(raw)
    assert "@bob (2026-04-20T03:00:00Z)" in out
    assert "thanks" in out


def test_text_format_uses_separator_headers() -> None:
    dumper = GitHubPRDumper(url="https://github.com/o/r/pull/1", output=None, fmt="text")
    raw = _make_raw(
        reviews=[{
            "login": "a", "is_bot": False, "state": "APPROVED",
            "body": "", "submitted_at": "2026-04-20T01:00:00Z",
        }],
        timeline_comments=[{
            "login": "b", "is_bot": False, "body": "hi",
            "created_at": "2026-04-20T03:00:00Z",
        }],
    )
    out = dumper.transform(raw)
    assert "--- REVIEWS ---" in out
    assert "--- TIMELINE COMMENTS ---" in out
    assert out.index("--- REVIEWS ---") < out.index("--- TIMELINE COMMENTS ---")
