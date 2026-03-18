"""Jira HTML pre-processing for better Markdown conversion.

Handles Jira-specific rendering quirks before passing to markdownify:
- {{monospace}} wiki markup left as raw text → <code>
- <tt> tags (Jira's monospace) → <code> for markdownify
- ${variable} broken across elements → rejoined
- Broken preformatted blocks (empty <pre> with content outside) → repaired
"""

from __future__ import annotations

import re


def preprocess_jira_html(html: str) -> str:
    """Apply all Jira HTML pre-processing steps."""
    html = convert_tt_to_code(html)
    html = rejoin_split_dollar_variables(html)
    html = convert_double_brace_monospace(html)
    html = repair_broken_preformatted(html)
    return html


def convert_tt_to_code(html: str) -> str:
    """Convert <tt>...</tt> (Jira monospace) to <code>...</code>."""
    html = re.sub(r"<tt\b([^>]*)>", r"<code\1>", html)
    html = re.sub(r"</tt>", "</code>", html)
    return html


def convert_double_brace_monospace(html: str) -> str:
    """Convert {{text}} wiki markup left by Jira renderer to <code>text</code>.

    Jira sometimes fails to render {{...}} to <tt> and leaves raw markup.
    Content may span across HTML tags (e.g. <p>, <br/>), which are stripped.
    """

    def _clean_match(match: re.Match[str]) -> str:
        inner = match.group(1)
        # Strip HTML tags that Jira injected inside the braces
        inner = re.sub(r"<[^>]+>", "", inner)
        # Collapse whitespace from tag removal
        inner = re.sub(r"\s+", " ", inner).strip()
        if not inner:
            return match.group(0)
        return f"<code>{inner}</code>"

    return re.sub(r"\{\{(.+?)\}\}", _clean_match, html, flags=re.DOTALL)


def rejoin_split_dollar_variables(html: str) -> str:
    r"""Rejoin ${variable} that Jira renderer split across elements.

    Jira breaks "${env}" into patterns like:
      $\n{env}          — dollar + newline + {var}
      $</p>\n{env}      — dollar at end of <p>, {var} as floating text
      $<br/>\n{env}     — dollar before <br/>
    """
    # Match $ followed by optional whitespace, optional HTML tags, then {word}
    return re.sub(
        r"\$\s*(?:<[^>]*>\s*)*\{(\w+)\}",
        r"${\1}",
        html,
    )


def repair_broken_preformatted(html: str) -> str:
    """Repair broken preformatted/code blocks.

    Jira sometimes emits:
      <div class="preformatted..."><pre></pre></div>
      actual code content with <br/>
      <div class="preformatted..."><pre></pre></div>

    This recombines them into proper <pre><code>content</code></pre>.
    """
    # Pattern: empty preformatted div, content, empty preformatted div
    pattern = (
        r'<div class="preformatted[^"]*"[^>]*>'
        r'\s*<div class="preformattedContent[^"]*"[^>]*>'
        r"\s*<pre></pre>\s*"
        r"</div>\s*</div>"
        r"(.*?)"
        r'<div class="preformatted[^"]*"[^>]*>'
        r'\s*<div class="preformattedContent[^"]*"[^>]*>'
        r"\s*<pre></pre>\s*"
        r"</div>\s*</div>"
    )

    def _rebuild(match: re.Match[str]) -> str:
        content = match.group(1)
        # Convert <br/> to newlines
        content = re.sub(r"<br\s*/?>", "\n", content)
        # Strip wrapping <p> tags that shouldn't be in code
        content = re.sub(r"</?p>", "\n", content)
        # Clean up excessive newlines
        content = content.strip()
        return f"<pre><code>{content}</code></pre>"

    return re.sub(pattern, _rebuild, html, flags=re.DOTALL)
