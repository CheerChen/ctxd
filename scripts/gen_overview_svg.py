"""Generate assets/ctxd-overview.svg in archdiagram style."""
from __future__ import annotations

import argparse
import re
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

INK = "#232f3e"
DIM = "#5f6b7a"
BAND = {"purple": "#f1eef8", "blue": "#e3eff9", "gray": "#f2f3f3"}
FONT = "'Amazon Ember',-apple-system,BlinkMacSystemFont,'Helvetica Neue',Arial,sans-serif"

STYLE = f"""
    text{{font-family:{FONT}}}
    text:where(:not([fill])){{fill:{INK}}}
    .lbl{{font-size:15px}}
    .lbl-b{{font-size:16px;font-weight:700}}
    .sub{{font-size:14px;fill:{DIM}}}
    .grp{{font-size:15px;font-weight:600;fill:{DIM}}}
    .role{{font-size:16px;font-weight:700}}
"""

DEFS_BASE = (
    '<marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" '
    'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
    f'<path d="M0,0 L10,5 L0,10 z" fill="{INK}"/></marker>'
)

RAW_ICONS = {
    "github": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1.03em\" height=\"1em\" viewBox=\"0 0 256 250\"><path fill=\"#161614\" d=\"M128.001 0C57.317 0 0 57.307 0 128.001c0 56.554 36.676 104.535 87.535 121.46c6.397 1.185 8.746-2.777 8.746-6.158c0-3.052-.12-13.135-.174-23.83c-35.61 7.742-43.124-15.103-43.124-15.103c-5.823-14.795-14.213-18.73-14.213-18.73c-11.613-7.944.876-7.78.876-7.78c12.853.902 19.621 13.19 19.621 13.19c11.417 19.568 29.945 13.911 37.249 10.64c1.149-8.272 4.466-13.92 8.127-17.116c-28.431-3.236-58.318-14.212-58.318-63.258c0-13.975 5-25.394 13.188-34.358c-1.329-3.224-5.71-16.242 1.24-33.874c0 0 10.749-3.44 35.21 13.121c10.21-2.836 21.16-4.258 32.038-4.307c10.878.049 21.837 1.47 32.066 4.307c24.431-16.56 35.165-13.12 35.165-13.12c6.967 17.63 2.584 30.65 1.255 33.873c8.207 8.964 13.173 20.383 13.173 34.358c0 49.163-29.944 59.988-58.447 63.157c4.591 3.972 8.682 11.762 8.682 23.704c0 17.126-.148 30.91-.148 35.126c0 3.407 2.304 7.398 8.792 6.14C219.37 232.5 256 184.537 256 128.002C256 57.307 198.691 0 128.001 0m-80.06 182.34c-.282.636-1.283.827-2.194.39c-.929-.417-1.45-1.284-1.15-1.922c.276-.655 1.279-.838 2.205-.399c.93.418 1.46 1.293 1.139 1.931m6.296 5.618c-.61.566-1.804.303-2.614-.591c-.837-.892-.994-2.086-.375-2.66c.63-.566 1.787-.301 2.626.591c.838.903 1 2.088.363 2.66m4.32 7.188c-.785.545-2.067.034-2.86-1.104c-.784-1.138-.784-2.503.017-3.05c.795-.547 2.058-.055 2.861 1.075c.782 1.157.782 2.522-.019 3.08m7.304 8.325c-.701.774-2.196.566-3.29-.49c-1.119-1.032-1.43-2.496-.726-3.27c.71-.776 2.213-.558 3.315.49c1.11 1.03 1.45 2.505.701 3.27m9.442 2.81c-.31 1.003-1.75 1.459-3.199 1.033c-1.448-.439-2.395-1.613-2.103-2.626c.301-1.01 1.747-1.484 3.207-1.028c1.446.436 2.396 1.602 2.095 2.622m10.744 1.193c.036 1.055-1.193 1.93-2.715 1.95c-1.53.034-2.769-.82-2.786-1.86c0-1.065 1.202-1.932 2.733-1.958c1.522-.03 2.768.818 2.768 1.868m10.555-.405c.182 1.03-.875 2.088-2.387 2.37c-1.485.271-2.861-.365-3.05-1.386c-.184-1.056.893-2.114 2.376-2.387c1.514-.263 2.868.356 3.061 1.403\"/></svg>",
    "slack": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1em\" height=\"1em\" viewBox=\"0 0 256 256\"><path fill=\"#e01e5a\" d=\"M53.841 161.32c0 14.832-11.987 26.82-26.819 26.82S.203 176.152.203 161.32c0-14.831 11.987-26.818 26.82-26.818H53.84zm13.41 0c0-14.831 11.987-26.818 26.819-26.818s26.819 11.987 26.819 26.819v67.047c0 14.832-11.987 26.82-26.82 26.82c-14.83 0-26.818-11.988-26.818-26.82z\"/><path fill=\"#36c5f0\" d=\"M94.07 53.638c-14.832 0-26.82-11.987-26.82-26.819S79.239 0 94.07 0s26.819 11.987 26.819 26.819v26.82zm0 13.613c14.832 0 26.819 11.987 26.819 26.819s-11.987 26.819-26.82 26.819H26.82C11.987 120.889 0 108.902 0 94.069c0-14.83 11.987-26.818 26.819-26.818z\"/><path fill=\"#2eb67d\" d=\"M201.55 94.07c0-14.832 11.987-26.82 26.818-26.82s26.82 11.988 26.82 26.82s-11.988 26.819-26.82 26.819H201.55zm-13.41 0c0 14.832-11.988 26.819-26.82 26.819c-14.831 0-26.818-11.987-26.818-26.82V26.82C134.502 11.987 146.489 0 161.32 0s26.819 11.987 26.819 26.819z\"/><path fill=\"#ecb22e\" d=\"M161.32 201.55c14.832 0 26.82 11.987 26.82 26.818s-11.988 26.82-26.82 26.82c-14.831 0-26.818-11.988-26.818-26.82V201.55zm0-13.41c-14.831 0-26.818-11.988-26.818-26.82c0-14.831 11.987-26.818 26.819-26.818h67.25c14.832 0 26.82 11.987 26.82 26.819s-11.988 26.819-26.82 26.819z\"/></svg>",
    "confluence": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1.05em\" height=\"1em\" viewBox=\"0 0 256 246\"><defs><linearGradient id=\"SVGvnhR7dox\" x1=\"99.14%\" x2=\"33.859%\" y1=\"112.708%\" y2=\"37.755%\"><stop offset=\"18%\" stop-color=\"#0052cc\"/><stop offset=\"100%\" stop-color=\"#2684ff\"/></linearGradient><linearGradient id=\"SVGgker3cTp\" x1=\".926%\" x2=\"66.18%\" y1=\"-12.582%\" y2=\"62.306%\"><stop offset=\"18%\" stop-color=\"#0052cc\"/><stop offset=\"100%\" stop-color=\"#2684ff\"/></linearGradient></defs><path fill=\"url(#SVGvnhR7dox)\" d=\"M9.26 187.33c-2.64 4.307-5.607 9.305-8.126 13.287a8.127 8.127 0 0 0 2.722 11.052l52.823 32.507a8.127 8.127 0 0 0 11.256-2.763c2.113-3.536 4.835-8.127 7.801-13.044c20.926-34.538 41.974-30.312 79.925-12.19l52.376 24.908a8.127 8.127 0 0 0 10.93-4.063l25.152-56.886a8.127 8.127 0 0 0-4.063-10.646c-11.052-5.201-33.034-15.562-52.823-25.111c-71.189-34.579-131.691-32.344-177.972 42.949\"/><path fill=\"url(#SVGgker3cTp)\" d=\"M246.115 58.232c2.641-4.307 5.607-9.305 8.127-13.287a8.127 8.127 0 0 0-2.723-11.052L198.696 1.386a8.127 8.127 0 0 0-11.58 2.682c-2.113 3.535-4.835 8.127-7.802 13.043c-20.926 34.538-41.974 30.313-79.925 12.19L47.176 4.515a8.127 8.127 0 0 0-10.93 4.063L11.093 65.465a8.127 8.127 0 0 0 4.063 10.645c11.052 5.202 33.035 15.563 52.823 25.112c71.351 34.538 131.854 32.222 178.135-42.99\"/></svg>",
    "jira": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1em\" height=\"1em\" viewBox=\"0 0 256 256\"><defs><linearGradient id=\"SVGSBI7obaC\" x1=\"98.031%\" x2=\"58.888%\" y1=\".161%\" y2=\"40.766%\"><stop offset=\"18%\" stop-color=\"#0052cc\"/><stop offset=\"100%\" stop-color=\"#2684ff\"/></linearGradient><linearGradient id=\"SVGHifZlbzE\" x1=\"100.665%\" x2=\"55.402%\" y1=\".455%\" y2=\"44.727%\"><stop offset=\"18%\" stop-color=\"#0052cc\"/><stop offset=\"100%\" stop-color=\"#2684ff\"/></linearGradient></defs><path fill=\"#2684ff\" d=\"M244.658 0H121.707a55.5 55.5 0 0 0 55.502 55.502h22.649V77.37c.02 30.625 24.841 55.447 55.466 55.467V10.666C255.324 4.777 250.55 0 244.658 0\"/><path fill=\"url(#SVGSBI7obaC)\" d=\"M183.822 61.262H60.872c.019 30.625 24.84 55.447 55.466 55.467h22.649v21.938c.039 30.625 24.877 55.43 55.502 55.43V71.93c0-5.891-4.776-10.667-10.667-10.667\"/><path fill=\"url(#SVGHifZlbzE)\" d=\"M122.951 122.489H0c0 30.653 24.85 55.502 55.502 55.502h22.72v21.867c.02 30.597 24.798 55.408 55.396 55.466V133.156c0-5.891-4.776-10.667-10.667-10.667\"/></svg>",
    "doc": "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<svg width=\"48px\" height=\"48px\" viewBox=\"0 0 48 48\" version=\"1.1\" xmlns=\"http://www.w3.org/2000/svg\" xmlns:xlink=\"http://www.w3.org/1999/xlink\">\n    <title>Icon-Resource/General-Resource/Res_Document_48_Light</title>\n    <g id=\"Icon-Resource/General-Resource/Res_Document_48\" stroke=\"none\" stroke-width=\"1\" fill=\"none\" fill-rule=\"evenodd\">\n        <path d=\"M15,20 L28,20 L28,18 L15,18 L15,20 Z M15,34 L28,34 L28,32 L15,32 L15,34 Z M15,27 L32,27 L32,25 L15,25 L15,27 Z M10,44 L10.007,4 L28,4 L28,13 C28,13.552 28.447,14 29,14 L38,14 L38.025,44 L10,44 Z M30,5.414 L36.586,12 L30,12 L30,5.414 Z M39.707,12.293 L29.707,2.293 C29.52,2.105 29.266,2 29,2 L10,2 C8.822,2 8,2.822 8,4 L8,44 C8,45.14 8.859,46 10,46 L38.025,46 C39.151,46 40,45.14 40,44 L40,13 C40,12.735 39.895,12.48 39.707,12.293 L39.707,12.293 Z\" id=\"Fill-1\" fill=\"#232F3D\"></path>\n    </g>\n</svg>",
}

AGENT_ICON = (
    48.0,
    48.0,
    "",
    '<rect x="6" y="8" width="36" height="32" rx="4" fill="none" stroke="#232F3D" stroke-width="2"/>'
    '<path d="M14,20 L21,25 L14,30" fill="none" stroke="#232F3D" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>'
    '<line x1="24" y1="30" x2="33" y2="30" stroke="#232F3D" stroke-width="2.2" stroke-linecap="round"/>',
)


def parse_icon(raw: str) -> tuple[float, float, str, str]:
    vb = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', raw)
    assert vb, "missing viewBox"
    inner = raw[raw.index(">", raw.index("<svg")) + 1 : raw.rindex("</svg>")]
    inner = re.sub(r"<title>.*?</title>", "", inner, flags=re.S)
    defs_match = re.search(r"<defs>(.*?)</defs>", inner, flags=re.S)
    defs = defs_match.group(1).strip() if defs_match else ""
    body = re.sub(r"<defs>.*?</defs>", "", inner, flags=re.S)
    return float(vb.group(1)), float(vb.group(2)), defs, " ".join(body.split())


def place_icon(vb_w: float, vb_h: float, body: str, cx: float, cy: float, size: float = 40) -> str:
    s = size / max(vb_w, vb_h)
    w, h = vb_w * s, vb_h * s
    return f'<g transform="translate({cx - w / 2:.1f},{cy - h / 2:.1f}) scale({s:.4f})">{body}</g>'


def band(x: int, y: int, w: int, h: int, color: str) -> str:
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{BAND[color]}"/>'


def service_box(x: int, y: int, w: int, h: int, label: str) -> str:
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="none" '
        f'stroke="{DIM}" stroke-width="1.5" stroke-dasharray="6,5"/>'
        f'<text x="{x + 18}" y="{y + 28}" class="grp">{escape(label)}</text>'
    )


def role(cx: int, y: int, text: str) -> str:
    w = int(round(10 * len(text) + 34))
    x = cx - w // 2
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="34" rx="8" fill="#ffffff" stroke="{INK}" stroke-width="1.8"/>'
        f'<text x="{cx}" y="{y + 23}" class="role" text-anchor="middle">{escape(text)}</text>'
    )


def source_row(x: int, y: int, w: int, h: int, icon_tup: tuple[float, float, str, str], label: str) -> str:
    vb_w, vb_h, _, body = icon_tup
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="#ffffff" stroke="{INK}" stroke-width="1.5"/>'
        + place_icon(vb_w, vb_h, body, x + 32, y + h / 2, 28)
        + f'<text x="{x + 60}" y="{y + h / 2 + 5:.0f}" class="lbl-b">{escape(label)}</text>'
    )


def box(x: int, y: int, w: int, h: int, title: str, subtitle: str) -> str:
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="#ffffff" stroke="{INK}" stroke-width="1.5"/>'
        f'<text x="{x + w / 2}" y="{y + h / 2 - 4:.0f}" class="lbl-b" text-anchor="middle">{escape(title)}</text>'
        f'<text x="{x + w / 2}" y="{y + h / 2 + 18:.0f}" class="sub" text-anchor="middle">{escape(subtitle)}</text>'
    )


def right_card(
    x: int,
    y: int,
    w: int,
    h: int,
    icon_tup: tuple[float, float, str, str],
    title: str,
    lines: list[str],
) -> str:
    vb_w, vb_h, _, body = icon_tup
    tx = x + 80
    total_h = 20 + len(lines) * 20
    top_y = y + (h - total_h) / 2 + 15
    out = (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="#ffffff" stroke="{INK}" stroke-width="1.5"/>'
        + place_icon(vb_w, vb_h, body, x + 42, y + h / 2, 40)
        + f'<text x="{tx}" y="{top_y:.0f}" class="lbl-b">{escape(title)}</text>'
    )
    for i, line_text in enumerate(lines):
        out += f'<text x="{tx}" y="{top_y + 22 + i * 20:.0f}" class="sub">{escape(line_text)}</text>'
    return out


def line(pts: list[tuple[int, int]]) -> str:
    d = "M" + " L".join(f"{x},{y}" for x, y in pts)
    return f'<path d="{d}" fill="none" stroke="{INK}" stroke-width="1.8" stroke-linejoin="round"/>'


def path(pts: list[tuple[int, int]]) -> str:
    return line(pts).replace(" stroke-linejoin=", ' marker-end="url(#ah)" stroke-linejoin=')


def build() -> str:
    ic_gh = parse_icon(RAW_ICONS["github"])
    ic_sl = parse_icon(RAW_ICONS["slack"])
    ic_cf = parse_icon(RAW_ICONS["confluence"])
    ic_jr = parse_icon(RAW_ICONS["jira"])
    ic_doc = parse_icon(RAW_ICONS["doc"])
    extra_defs = [ic_gh[2], ic_sl[2], ic_cf[2], ic_jr[2], ic_doc[2]]

    p: list[str] = []

    # 1. Left column: Work URLs
    p.append(band(36, 28, 284, 324, "gray"))
    p.append(service_box(36, 28, 284, 324, "Work URLs"))
    sources = [
        (ic_gh, "GitHub PR"),
        (ic_sl, "Slack Thread"),
        (ic_cf, "Confluence"),
        (ic_jr, "Jira Issue"),
    ]
    src_ys: list[int] = []
    for i, (icon_tup, label) in enumerate(sources):
        ry = 72 + i * 66
        src_ys.append(ry + 26)
        p.append(source_row(58, ry, 240, 52, icon_tup, label))

    # 2. Middle column: ctxd
    p.append(band(416, 68, 304, 244, "blue"))
    p.append(service_box(416, 68, 304, 244, ""))
    p.append(role(568, 51, "ctxd"))
    p.append(box(442, 108, 252, 72, "One-command bulk export", "CLI + Agent Skill"))
    p.append(box(442, 204, 252, 72, "Full context preserved", "comments · metadata · files"))

    # 3. Right column: LLM-ready Output
    p.append(band(816, 28, 348, 324, "purple"))
    p.append(service_box(816, 28, 348, 324, "LLM-ready Output"))
    p.append(
        right_card(
            840,
            78,
            300,
            106,
            ic_doc,
            "Clean Markdown",
            ["save, diff, or archive on disk", "with local images & attachments"],
        )
    )
    p.append(
        right_card(
            840,
            218,
            300,
            106,
            AGENT_ICON,
            "Ready for LLMs & Agents",
            ["Claude Code · Codex · Chat", "no multi-turn connector calls"],
        )
    )
    p.append(path([(990, 184), (990, 218)]))

    # Orthogonal connectors
    mid_y = 190
    for sy in src_ys:
        p.append(line([(298, sy), (358, sy)]))
    p.append(line([(358, src_ys[0]), (358, src_ys[-1])]))
    p.append(path([(358, mid_y), (416, mid_y)]))
    p.append(path([(720, mid_y), (776, mid_y), (776, 131), (840, 131)]))

    defs_block = "<defs>" + DEFS_BASE + "".join(d for d in extra_defs if d) + "</defs>"
    title = "ctxd overview"
    desc = (
        "ctxd exports GitHub PR, Slack Thread, Confluence, and Jira Issue URLs in one command into clean, "
        "local Markdown with comments, metadata, and attachments ready for any LLM or coding agent."
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="380" viewBox="0 0 1200 380" role="img" aria-labelledby="title desc">\n'
        f'  <title id="title">{escape(title)}</title>\n'
        f'  <desc id="desc">{escape(desc)}</desc>\n'
        f"  <style>{STYLE}  </style>\n"
        f"  {defs_block}\n"
        f'  <rect width="1200" height="380" fill="#ffffff"/>\n'
        + "\n".join(p)
        + "\n</svg>\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "assets" / "ctxd-overview.svg")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build(), encoding="utf-8")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
