"""Markdown formatter helpers."""


def section(title: str, body: str, level: int = 2) -> str:
    return f"{'#' * level} {title}\n\n{body}\n"
