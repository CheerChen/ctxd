"""Plain text formatter helpers."""


def section(title: str, body: str) -> str:
    return f"--- {title} ---\n{body}\n"
