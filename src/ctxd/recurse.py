"""Cross-source recursive expansion.

After rendering a primary source, scan its text for supported URLs
(Slack / GitHub PR / Confluence / Jira) and render those too, appending
the results as a labelled appendix. This lets a single ``ctxd`` call pull
in the full context behind every link a conversation references, without
the LLM having to issue follow-up fetches.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

from ctxd.auth import AuthError
from ctxd.dumpers import ConfluenceDumper, GitHubPRDumper, JiraDumper, SlackDumper
from ctxd.router import Source, detect, parse_slack_thread_url

# Cap how many child URLs we recurse into per level. Prevents a Jira issue
# that links 50 other issues from exploding the output.
MAX_CHILDREN_PER_LEVEL = 5

# Reuse the router's compiled patterns to find supported URLs in arbitrary text.
_URL_RE = re.compile(r"https?://[^\s<>\]\)|]+")


def _is_recurseable(url: str) -> bool:
    """Stricter check than detect(): ensures the URL can actually be parsed.

    detect() uses broad patterns (e.g. any Slack /archives/ URL) that match
    channel URLs which aren't valid thread targets. This filters those out
    so they don't waste a slot in the recursion cap.
    """
    try:
        source = detect(url)
    except ValueError:
        return False
    # Slack channel URLs (e.g. /archives/C123 without /p<ts>) match detect()
    # but parse_slack_thread_url rejects them. Filter them out here.
    if source is Source.SLACK_THREAD:
        try:
            parse_slack_thread_url(url)
        except ValueError:
            return False
    return True


def extract_supported_urls(text: str, exclude: set[str] | None = None) -> list[str]:
    """Return supported URLs found in *text*, de-duplicated, preserving order.

    *exclude* URLs (typically the parent URL itself) are skipped.
    Non-supported URLs (e.g. plain web links) are ignored.
    """
    exclude = exclude or set()
    seen: set[str] = set()
    results: list[str] = []
    for match in _URL_RE.finditer(text):
        url = match.group(0).rstrip(".,;:!?")  # strip trailing punctuation
        if url in exclude or url in seen:
            continue
        if not _is_recurseable(url):
            continue
        seen.add(url)
        results.append(url)
    return results


@dataclass
class _RecurseOpts:
    """Common options propagated to child dumpers."""

    fmt: str
    quiet: bool
    verbose: bool


def _build_dumper(url: str, opts: _RecurseOpts):
    """Construct the appropriate dumper for *url* with default source-specific flags."""
    source = detect(url)
    if source is Source.SLACK_THREAD:
        return SlackDumper(
            url=url, output=None, fmt=opts.fmt, quiet=opts.quiet, verbose=opts.verbose
        )
    if source is Source.GITHUB_PR:
        return GitHubPRDumper(
            url=url, output=None, fmt=opts.fmt, quiet=opts.quiet, verbose=opts.verbose
        )
    if source is Source.CONFLUENCE:
        return ConfluenceDumper(
            url=url, output=None, fmt=opts.fmt, quiet=opts.quiet, verbose=opts.verbose
        )
    return JiraDumper(
        url=url, output=None, fmt=opts.fmt, quiet=opts.quiet, verbose=opts.verbose
    )


def _log(quiet: bool, message: str) -> None:
    if not quiet:
        print(message, file=sys.stderr)


def render_with_recurse(
    primary_dumper,
    depth: int,
    seen: set[str] | None = None,
    _level: int = 0,
) -> str:
    """Render *primary_dumper* and recursively expand supported URLs in its output.

    *depth* is the remaining recursion depth (0 = no recursion).
    *seen* tracks URLs already rendered to avoid duplicate fetches across levels.
    """
    if seen is None:
        seen = set()

    primary_url = primary_dumper.url
    seen.add(primary_url)

    content = primary_dumper.render()

    if depth <= 0:
        return content

    child_urls = extract_supported_urls(content, exclude=seen)
    truncated = 0
    if len(child_urls) > MAX_CHILDREN_PER_LEVEL:
        truncated = len(child_urls) - MAX_CHILDREN_PER_LEVEL
        child_urls = child_urls[:MAX_CHILDREN_PER_LEVEL]

    if not child_urls and truncated == 0:
        return content

    opts = _RecurseOpts(
        fmt=primary_dumper.fmt, quiet=primary_dumper.quiet, verbose=primary_dumper.verbose
    )

    appendix: list[str] = []
    index = 0
    for child_url in child_urls:
        index += 1
        prefix = f"[{_level}.{index}]" if _level > 0 else f"[{index}]"
        seen.add(child_url)

        _log(opts.quiet, f"  ↳ {prefix} recursing into {child_url}")

        try:
            child_dumper = _build_dumper(child_url, opts)
            child_content = render_with_recurse(
                child_dumper, depth=depth - 1, seen=seen, _level=_level + 1
            )
            appendix.append(f"> ↳ {prefix} recursed from {child_url}\n\n{child_content}")
        except AuthError as exc:
            appendix.append(f"> ↳ {prefix} recursed from {child_url} — skipped: {exc}")
        except Exception as exc:
            appendix.append(f"> ↳ {prefix} recursed from {child_url} — skipped: {exc}")

    if truncated:
        appendix.append(
            f"> ↳ ... {truncated} more supported link(s) truncated "
            f"(cap {MAX_CHILDREN_PER_LEVEL} per level)"
        )

    if not appendix:
        return content

    return content + "\n\n---\n\n" + "\n\n---\n\n".join(appendix) + "\n"
