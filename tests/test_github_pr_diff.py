from __future__ import annotations

from ctxd.dumpers.github_pr import GitHubPRDumper


def _make_dumper(diff_mode: str = "compact") -> GitHubPRDumper:
    d = GitHubPRDumper(
        url="https://github.com/o/r/pull/1",
        output=None,
        fmt="md",
        diff_mode=diff_mode,
    )
    d.owner, d.repo, d.pr_number = "o", "r", "1"
    return d


_UNIFIED_SAMPLE = """diff --git a/foo.py b/foo.py
index 111..222 100644
--- a/foo.py
+++ b/foo.py
@@ -10,3 +10,4 @@ def f():
 unchanged
-old
+new
+added
diff --git a/bar.py b/bar.py
index 333..444 100644
--- a/bar.py
+++ b/bar.py
@@ -1,2 +1,1 @@
-gone
 kept
"""


def test_compact_diff_parses_unified_and_summarizes() -> None:
    out = _make_dumper("compact")._generate_compact_diff(_UNIFIED_SAMPLE)
    assert "foo.py" in out
    assert "bar.py" in out
    assert "hunk 1" in out
    assert "@ def f():" in out
    assert "Summary: 2 insertion(s)(+), 2 deletion(s)(-)" in out


def test_full_diff_returns_unified_verbatim(monkeypatch) -> None:
    dumper = _make_dumper("full")
    monkeypatch.setattr(dumper, "_fetch_unified_diff", lambda: _UNIFIED_SAMPLE)
    assert dumper._generate_diff() == _UNIFIED_SAMPLE


def test_full_diff_empty_returns_placeholder(monkeypatch) -> None:
    dumper = _make_dumper("full")
    monkeypatch.setattr(dumper, "_fetch_unified_diff", lambda: "")
    assert dumper._generate_diff() == GitHubPRDumper._NO_DIFF


def test_stat_diff_uses_pulls_files_api(monkeypatch) -> None:
    dumper = _make_dumper("stat")
    monkeypatch.setattr(
        dumper,
        "_gh_api_paginate",
        lambda path: [
            {"filename": "foo.py", "additions": 5, "deletions": 2},
            {"filename": "bar/baz.py", "additions": 0, "deletions": 3},
        ],
    )
    out = dumper._generate_diff()
    assert "foo.py" in out
    assert "bar/baz.py" in out
    assert "+5/-2" in out
    assert "+0/-3" in out
    assert "Summary: 2 file(s) changed, 5 insertion(s)(+), 5 deletion(s)(-)" in out


def test_stat_diff_empty_returns_placeholder(monkeypatch) -> None:
    dumper = _make_dumper("stat")
    monkeypatch.setattr(dumper, "_gh_api_paginate", lambda path: [])
    assert dumper._generate_diff() == GitHubPRDumper._NO_DIFF
