"""ctxd CLI entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from click.core import ParameterSource

from ctxd import __version__
from ctxd.auth import AuthError
from ctxd.concurrency import configure as configure_concurrency
from ctxd.dumpers import ConfluenceDumper, GitHubPRDumper, JiraDumper, SlackDumper
from ctxd.profiling import emit_report, enable_profiling
from ctxd.recurse import render_with_recurse
from ctxd.router import Source, detect


@click.command(context_settings={"help_option_names": ["-h", "--help"], "allow_interspersed_args": True})
@click.argument("url_or_cmd", required=False)
@click.argument("shell", required=False)
@click.option("-o", "--output", type=click.Path(path_type=Path), help="Output file or directory")
@click.option("-O", "--auto-output", is_flag=True, default=False,
              help="Auto-generate output path by source (mutually exclusive with -o)")
@click.option("-f", "--format", "fmt", type=click.Choice(["text", "md"]), default="md", show_default=True)
@click.option("-q", "--quiet", is_flag=True, help="Silence progress logs to stderr")
@click.option("-v", "--verbose", is_flag=True, help="Verbose logs to stderr")
@click.option("-d", "--diff-mode", type=click.Choice(["full", "compact", "stat"]), default="compact", show_default=True)
@click.option("--clean-body/--no-clean-body", default=True, show_default=True)
@click.option("--no-bots", is_flag=True, default=False,
              help="GitHub PR: drop bot-authored reviews/comments (default: keep all bots)")
@click.option("--download-files", is_flag=True, default=False)
@click.option("--raw", is_flag=True, default=False, help="Keep original Slack mrkdwn")
@click.option("-r", "--recursive/--no-recursive", default=False, show_default=True,
              help="Confluence: also export child pages (requires -o or -O)")
@click.option("-i", "--include-images/--no-include-images", default=False, show_default=True,
              help="Confluence: download referenced images (requires -o or -O)")
@click.option("--all-attachments", is_flag=True, default=False)
@click.option("--obsidian", is_flag=True, default=False,
              help="Confluence/Jira: write an Obsidian note (frontmatter + body); requires -o or -O")
@click.option("--debug", is_flag=True, default=False)
@click.option("--profile", "profile", is_flag=True, default=False,
              help="Print HTTP/subprocess/stage timing breakdown to stderr after dump")
@click.option("--max-concurrency", "max_concurrency", type=click.IntRange(1, 32),
              default=5, show_default=True,
              help="Max concurrent HTTP / subprocess fan-out (Confluence pages, gh API)")
@click.option("--recurse-depth", "recurse_depth", type=click.IntRange(0, 2),
              default=1, show_default=True,
              help="Cross-source recursion depth: expand supported URLs found in the output (0=off)")
@click.option("--no-recurse", is_flag=True, default=False,
              help="Disable cross-source recursion (equivalent to --recurse-depth 0)")
@click.version_option(__version__, prog_name="ctxd")
@click.pass_context
def main(
    ctx: click.Context,
    url_or_cmd: str | None,
    shell: str | None,
    output: Path | None,
    auto_output: bool,
    fmt: str,
    quiet: bool,
    verbose: bool,
    diff_mode: str,
    clean_body: bool,
    no_bots: bool,
    download_files: bool,
    raw: bool,
    recursive: bool,
    include_images: bool,
    all_attachments: bool,
    obsidian: bool,
    debug: bool,
    profile: bool,
    max_concurrency: int,
    recurse_depth: int,
    no_recurse: bool,
) -> None:
    """Unified context dumper for GitHub PR, Slack thread, Confluence, and Jira.

    Supports:
    - ctxd <url> [options]
    - ctxd init <zsh|bash|fish>
    """
    if url_or_cmd == "init":
        _emit_shell_alias(shell)
        return

    if profile:
        enable_profiling()
    configure_concurrency(max_concurrency)

    if shell:
        raise click.UsageError(f"Unexpected argument: {shell}")

    url = url_or_cmd
    if not url:
        raise click.UsageError("URL is required. Or use: ctxd init <zsh|bash|fish>")

    if output is not None and auto_output:
        raise click.UsageError("-o/--output and -O/--auto-output are mutually exclusive")

    try:
        source = detect(url)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    if obsidian:
        _validate_obsidian_flags(
            source=source,
            output=output,
            auto_output=auto_output,
            recursive=recursive,
            fmt=fmt,
        )

    # Auto-quiet when stderr is being piped/redirected (not a TTY), unless the
    # user explicitly asked for quiet or verbose.
    if (
        not verbose
        and ctx.get_parameter_source("quiet") == ParameterSource.DEFAULT
        and not _stderr_is_tty()
    ):
        quiet = True

    output_str = str(output) if output else None

    if source is Source.CONFLUENCE:
        _validate_confluence_flags(
            url=url,
            output=output,
            auto_output=auto_output,
            recursive=recursive,
            include_images=include_images,
            all_attachments=all_attachments,
        )
        dumper = ConfluenceDumper(
            url=url,
            output=output_str,
            fmt=fmt,
            quiet=quiet,
            verbose=verbose,
            recursive=recursive,
            include_images=include_images,
            all_attachments=all_attachments,
            debug=debug,
            obsidian_mode=obsidian,
            obsidian_auto_output=auto_output and obsidian,
        )
    elif source is Source.GITHUB_PR:
        dumper = GitHubPRDumper(
            url=url,
            output=output_str,
            fmt=fmt,
            quiet=quiet,
            verbose=verbose,
            diff_mode=diff_mode,
            clean_body=clean_body,
            no_bots=no_bots,
        )
    elif source is Source.JIRA:
        dumper = JiraDumper(
            url=url,
            output=output_str,
            fmt=fmt,
            quiet=quiet,
            verbose=verbose,
            debug=debug,
            obsidian_mode=obsidian,
            obsidian_auto_output=auto_output and obsidian,
        )
    else:
        dumper = SlackDumper(
            url=url,
            output=output_str,
            fmt=fmt,
            quiet=quiet,
            verbose=verbose,
            download_files=download_files,
            raw=raw,
        )

    if no_recurse:
        recurse_depth = 0

    # Cross-source recursion is incompatible with Confluence directory export
    # (which writes a page tree to disk) and with Obsidian single-note mode.
    use_recurse = recurse_depth > 0 and not obsidian
    if use_recurse and source is Source.CONFLUENCE and (output is not None or auto_output):
        if not quiet:
            click.echo(
                "ℹ Cross-source recursion disabled for Confluence directory export "
                "(use stdout, or omit -o/-O to enable).",
                err=True,
            )
        use_recurse = False

    resolved_output: Path | None = output
    if auto_output and not obsidian:
        resolved_output = Path(dumper.default_filename())

    if use_recurse:
        # render_with_recurse collects content as a string; we handle the
        # writing ourselves. dumper.output is kept for transform's internal
        # use (e.g. SlackDumper attachment base dir) but render() won't write.
        dumper.output = str(resolved_output) if resolved_output else None
        if resolved_output and source is not Source.CONFLUENCE:
            resolved_output.parent.mkdir(parents=True, exist_ok=True)

        try:
            try:
                content = render_with_recurse(dumper, depth=recurse_depth)
            except AuthError as exc:
                raise click.ClickException(str(exc)) from exc
            except Exception as exc:
                raise click.ClickException(str(exc)) from exc

            if resolved_output:
                with open(resolved_output, "w", encoding="utf-8") as handle:
                    handle.write(content)
                dumper.log(f"✅ Saved to {resolved_output}")
            else:
                sys.stdout.write(content)
        finally:
            emit_report()
        return

    if obsidian:
        pass  # dumper handles its own path resolution and parent dir creation
    elif resolved_output and source is Source.CONFLUENCE:
        resolved_output.mkdir(parents=True, exist_ok=True)
    elif resolved_output:
        resolved_output.parent.mkdir(parents=True, exist_ok=True)

    dumper.output = str(resolved_output) if resolved_output else None

    try:
        try:
            dumper.dump()
        except AuthError as exc:
            raise click.ClickException(str(exc)) from exc
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc
    finally:
        emit_report()


def _stderr_is_tty() -> bool:
    return sys.stderr.isatty()


def _emit_shell_alias(shell: str | None) -> None:
    if shell is None:
        raise click.UsageError("Missing shell. Use: ctxd init <zsh|bash|fish>")
    if shell not in {"zsh", "bash", "fish"}:
        raise click.UsageError(f"Unsupported shell: {shell}. Use one of: zsh, bash, fish")

    if shell == "zsh":
        click.echo("alias ctxd='noglob ctxd'")
        click.echo("alias ctx='noglob ctxd'")
        return

    if shell == "bash":
        click.echo("alias ctx=ctxd")
        return

    click.echo("alias ctx ctxd")


def _validate_obsidian_flags(
    source: Source,
    output: Path | None,
    auto_output: bool,
    recursive: bool,
    fmt: str,
) -> None:
    if source not in (Source.CONFLUENCE, Source.JIRA):
        raise click.UsageError("--obsidian only supports Confluence and Jira URLs")
    if output is None and not auto_output:
        raise click.UsageError("--obsidian requires -o <file> or -O")
    if recursive:
        raise click.UsageError(
            "--obsidian does not support -r/--recursive (export pages individually)"
        )
    if fmt != "md":
        raise click.UsageError("--obsidian requires markdown format (incompatible with -f text)")


def _validate_confluence_flags(
    url: str,
    output: Path | None,
    auto_output: bool,
    recursive: bool,
    include_images: bool,
    all_attachments: bool,
) -> None:
    if output is not None or auto_output:
        return

    used: list[str] = []
    if recursive:
        used.append("-r")
    if include_images:
        used.append("-i")
    if all_attachments:
        used.append("--all-attachments")
    if not used:
        return

    flags = " ".join(used)
    raise click.UsageError(
        f"{flags} requires -o <dir> or -O (Confluence writes a directory tree / images to disk).\n"
        f"Try:   ctxd {url} {flags} -o <dir>\n"
        f"Or:    ctxd {url} {flags} -O\n"
        f"Or omit the flags for single-page stdout: ctxd {url}"
    )
