"""Control character sanitization for fetched content.

Removes ANSI escape sequences, OSC sequences, and other non-printable
control characters that serve no purpose in Markdown output but can
interfere with downstream rendering or LLM processing.

Tracks how many characters were removed so the summary can report it.
"""

from __future__ import annotations

import re

# ANSI CSI sequences: ESC [ ... letter
# Covers SGR (colors), cursor movement, erase, etc.
_CSI_PATTERN = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")

# OSC sequences: ESC ] ... (BEL or ST)
# Covers terminal title setting, hyperlinks, etc.
_OSC_PATTERN = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")

# Other common escape sequences (ESC + single char)
# Excludes \x1b (ESC itself, handled above) and \t \n \r (legitimate)
_SINGLE_ESC_PATTERN = re.compile(r"\x1b[=>NMcDM]")

# Remaining control chars (0x00-0x08, 0x0B, 0x0C, 0x0E-0x1F, 0x7F)
# Excludes \t (0x09), \n (0x0A), \r (0x0D) which are legitimate.
_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_control_chars(text: str) -> tuple[str, int]:
    """Remove ANSI/OSC/control characters from *text*.

    Returns ``(cleaned_text, removed_count)`` where *removed_count* is
    the total number of characters removed (sequence characters, not
    visible characters).

    Legitimate whitespace (\\t, \\n, \\r) is preserved.
    """
    if not text:
        return text, 0

    original_len = len(text)

    # Remove escape sequences first (they span multiple chars)
    result = _OSC_PATTERN.sub("", text)
    result = _CSI_PATTERN.sub("", result)
    result = _SINGLE_ESC_PATTERN.sub("", result)

    # Remove remaining single control characters
    result = _CONTROL_CHAR_PATTERN.sub("", result)

    removed = original_len - len(result)
    return result, removed
