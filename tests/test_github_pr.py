from ctxd.dumpers.github_pr import GitHubPRDumper


def test_clean_pr_body_extracts_file_walkthrough() -> None:
    body = """
<details>
<summary>File Walkthrough</summary>
<strong>foo.py</strong><code>refactor parser</code>
<a href=\"x\"> +10/-2 </a>
</details>
"""
    cleaned = GitHubPRDumper.clean_pr_body(body)
    assert "[File Changes]" in cleaned
    assert "foo.py: refactor parser (+10/-2)" in cleaned


def test_clean_pr_body_strips_html() -> None:
    body = "Hello <a href=\"x\">world</a> &amp; all&nbsp;"
    cleaned = GitHubPRDumper.clean_pr_body(body)
    assert "<a" not in cleaned
    assert "Hello world & all" in cleaned
