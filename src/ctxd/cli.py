"""ctxd CLI entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from click.core import ParameterSource

from ctxd import __version__
from ctxd.auth import AuthError
from ctxd.dumpers import ConfluenceDumper, GitHubPRDumper, JiraDumper, SlackDumper
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
@click.option("--debug", is_flag=True, default=False)
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
    debug: bool,
) -> None:
    """Unified context dumper for GitHub PR, Slack thread, Confluence, and Jira.

    Supports:
    - ctxd <url> [options]
    - ctxd init <zsh|bash|fish>
    """
    if url_or_cmd == "init":
        _emit_shell_alias(shell)
        return

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

    resolved_output: Path | None = output
    if auto_output:
        resolved_output = Path(dumper.default_filename())

    if resolved_output and source is Source.CONFLUENCE:
        resolved_output.mkdir(parents=True, exist_ok=True)
    elif resolved_output:
        resolved_output.parent.mkdir(parents=True, exist_ok=True)

    dumper.output = str(resolved_output) if resolved_output else None

    try:
        dumper.dump()
    except AuthError as exc:
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


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
