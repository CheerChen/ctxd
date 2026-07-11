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
from ctxd.profiling import record, timed
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
    max_chars: int = 0
    max_file_size: int = 0
    max_run_size: int = 0
    run_budget: object = None  # Shared RunBudget across all dumpers in the recursion tree


def _build_dumper(url: str, opts: _RecurseOpts):
    """Construct the appropriate dumper for *url* with default source-specific flags."""
    from ctxd.download_limits import DEFAULT_MAX_FILE_BYTES, DEFAULT_MAX_RUN_BYTES

    # Resolve size limits: 0 means use module default.
    max_file_size = opts.max_file_size if opts.max_file_size != 0 else DEFAULT_MAX_FILE_BYTES
    max_run_size = opts.max_run_size if opts.max_run_size != 0 else DEFAULT_MAX_RUN_BYTES

    source = detect(url)
    if source is Source.SLACK_THREAD:
        d = SlackDumper(
            url=url, output=None, fmt=opts.fmt, quiet=opts.quiet, verbose=opts.verbose,
            max_chars=opts.max_chars, max_file_size=max_file_size, max_run_size=max_run_size,
        )
    elif source is Source.GITHUB_PR:
        d = GitHubPRDumper(
            url=url, output=None, fmt=opts.fmt, quiet=opts.quiet, verbose=opts.verbose,
            max_chars=opts.max_chars, max_file_size=max_file_size, max_run_size=max_run_size,
        )
    elif source is Source.CONFLUENCE:
        d = ConfluenceDumper(
            url=url, output=None, fmt=opts.fmt, quiet=opts.quiet, verbose=opts.verbose,
            max_chars=opts.max_chars, max_file_size=max_file_size, max_run_size=max_run_size,
        )
    else:
        d = JiraDumper(
            url=url, output=None, fmt=opts.fmt, quiet=opts.quiet, verbose=opts.verbose,
            max_chars=opts.max_chars, max_file_size=max_file_size, max_run_size=max_run_size,
        )
    # Share the parent's run budget so all downloads in the recursion
    # tree count against the same per-run cap.
    if opts.run_budget is not None:
        d._run_budget = opts.run_budget
    return d


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

    The primary dumper's ``summary`` is the canonical aggregate: child
    dumpers' summaries are merged into it so the root summary reflects
    the full recursion tree.
    """
    if seen is None:
        seen = set()

    primary_url = primary_dumper.url
    seen.add(primary_url)

    content = primary_dumper.render()

    # The primary resource itself counts as 1 fetched + 1 rendered.
    # render() already set resources_fetched/resources_rendered for the
    # primary source, but if the dumper's render() didn't set it (e.g.
    # test stub), ensure it.
    if primary_dumper.summary.resources_fetched == 0:
        primary_dumper.summary.resources_fetched = 1
    if primary_dumper.summary.resources_rendered == 0:
        primary_dumper.summary.resources_rendered = 1

    if depth <= 0:
        return content

    all_child_urls = extract_supported_urls(content, exclude=seen)
    truncated = 0
    if len(all_child_urls) > MAX_CHILDREN_PER_LEVEL:
        truncated = len(all_child_urls) - MAX_CHILDREN_PER_LEVEL
        child_urls = all_child_urls[:MAX_CHILDREN_PER_LEVEL]
    else:
        child_urls = all_child_urls

    # P0: feed per-level discovery / render / truncation counts to the profiler
    # so --profile can answer "how many links did we find, render, and drop?"
    record(f"recurse.L{_level}.discovered", count=len(all_child_urls))
    record(f"recurse.L{_level}.rendered", count=len(child_urls))
    record(f"recurse.L{_level}.truncated", count=truncated)

    if not child_urls and truncated == 0:
        return content

    opts = _RecurseOpts(
        fmt=primary_dumper.fmt, quiet=primary_dumper.quiet, verbose=primary_dumper.verbose,
        max_chars=getattr(primary_dumper, "max_chars", 0),
        max_file_size=getattr(primary_dumper, "max_file_size", 0),
        max_run_size=getattr(primary_dumper, "max_run_size", 0),
        # Use the run_budget property (not _run_budget) so it is lazily
        # initialised — reading the private attribute directly would
        # return None when the parent hasn't downloaded anything yet.
        run_budget=primary_dumper.run_budget if hasattr(primary_dumper, "run_budget") else None,
    )

    appendix: list[str] = []
    index = 0
    for child_url in child_urls:
        index += 1
        prefix = f"[{_level}.{index}]" if _level > 0 else f"[{index}]"
        seen.add(child_url)

        _log(opts.quiet, f"  ↳ {prefix} recursing into {child_url}")

        # P0: time each child fetch+render under a level-tagged label so the
        # profile table separates per-child latency from the primary fetch.
        try:
            child_dumper = _build_dumper(child_url, opts)
            with timed(f"recurse.L{_level}.child{index}"):
                child_content = render_with_recurse(
                    child_dumper, depth=depth - 1, seen=seen, _level=_level + 1
                )
            appendix.append(f"> ↳ {prefix} recursed from {child_url}\n\n{child_content}")
            # Merge the child's summary into the root so counts propagate.
            # resources_fetched and resources_rendered accumulate (each
            # child is a distinct source resource).  artifacts_written
            # does NOT increase — child content is embedded into the same
            # output artifact as the parent.
            child_summary = child_dumper.summary
            primary_dumper.summary.resources_fetched += child_summary.resources_fetched
            primary_dumper.summary.resources_rendered += child_summary.resources_rendered
            primary_dumper.summary.skipped += child_summary.skipped
            primary_dumper.summary.failed += child_summary.failed
            primary_dumper.summary.truncated += child_summary.truncated
            primary_dumper.summary.notes.extend(child_summary.notes)
            primary_dumper.summary.items.extend(child_summary.items)
        except AuthError as exc:
            appendix.append(f"> ↳ {prefix} recursed from {child_url} — skipped: {exc}")
            primary_dumper.summary.skipped += 1
            primary_dumper.summary.add_note(f"child {child_url} skipped: {exc}")
        except Exception as exc:
            appendix.append(f"> ↳ {prefix} recursed from {child_url} — skipped: {exc}")
            primary_dumper.summary.failed += 1
            primary_dumper.summary.add_note(f"child {child_url} failed: {exc}")

    if truncated:
        # P1: list the truncated URLs so the LLM (or a human reviewing the
        # dump) can decide whether to follow up on a specific skipped link
        # instead of seeing only an opaque count.
        primary_dumper.summary.truncated += truncated
        truncated_urls = all_child_urls[MAX_CHILDREN_PER_LEVEL:]
        lines = [
            f"> ↳ ... {truncated} more supported link(s) truncated "
            f"(cap {MAX_CHILDREN_PER_LEVEL} per level):"
        ]
        for u in truncated_urls:
            lines.append(f">   - {u}")
        appendix.append("\n".join(lines))

    if not appendix:
        return content

    return content + "\n\n---\n\n" + "\n\n---\n\n".join(appendix) + "\n"
