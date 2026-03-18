"""ctxd CLI entrypoint."""

from __future__ import annotations

from pathlib import Path

import click

from ctxd import __version__
from ctxd.auth import AuthError
from ctxd.dumpers import ConfluenceDumper, GitHubPRDumper, JiraDumper, SlackDumper
from ctxd.router import Source, detect


@click.command(context_settings={"help_option_names": ["-h", "--help"], "allow_interspersed_args": True})
@click.argument("url_or_cmd", required=False)
@click.argument("shell", required=False)
@click.option("-o", "--output", type=click.Path(path_type=Path), help="Output file or directory")
@click.option("-f", "--format", "fmt", type=click.Choice(["text", "md"]), default="md", show_default=True)
@click.option("-q", "--quiet", is_flag=True, help="Silence progress logs to stderr")
@click.option("-v", "--verbose", is_flag=True, help="Verbose logs to stderr")
@click.option("-d", "--diff-mode", type=click.Choice(["full", "compact", "stat"]), default="compact", show_default=True)
@click.option("--clean-body/--no-clean-body", default=True, show_default=True)
@click.option("--download-files", is_flag=True, default=False)
@click.option("--raw", is_flag=True, default=False, help="Keep original Slack mrkdwn")
@click.option("-r", "--recursive/--no-recursive", default=True, show_default=True)
@click.option("-i", "--include-images/--no-include-images", default=True, show_default=True)
@click.option("--all-attachments", is_flag=True, default=False)
@click.option("--debug", is_flag=True, default=False)
@click.version_option(__version__, prog_name="ctxd")
def main(
    url_or_cmd: str | None,
    shell: str | None,
    output: Path | None,
    fmt: str,
    quiet: bool,
    verbose: bool,
    diff_mode: str,
    clean_body: bool,
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

    try:
        source = detect(url)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    output_str = str(output) if output else None

    if source is Source.CONFLUENCE:
        _validate_confluence_stdout_rules(
            output=output,
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
    if output and output_str == "auto":
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


def _validate_confluence_stdout_rules(
    output: Path | None,
    recursive: bool,
    include_images: bool,
    all_attachments: bool,
) -> None:
    if output is not None:
        return

    if recursive or include_images or all_attachments:
        raise click.UsageError(
            "Confluence recursive/image export requires -o <dir>. "
            "For stdout, use --no-recursive --no-include-images."
        )
