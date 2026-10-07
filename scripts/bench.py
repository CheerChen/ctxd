"""Repeatable ctxd benchmark.

Reads scenarios from ``~/.config/ctxd/bench-targets`` (real URLs stay out of
the repo), runs each one against one or more git refs, and writes:

- ``.bench-out/<date>-<sha>/results.json`` — every run, raw (gitignored)
- ``bench/results/<date>-<sha>.md``         — the summary that gets committed

Each ref is built into its own uv-managed environment straight from the git
commit (``uvx --from git+file://...@<sha>``), so the working tree never
leaks into a measurement and no worktree is needed.  Runs of different refs
are interleaved (A B A B ...) so network drift hits every ref equally.

Targets file format, one scenario per line::

    id | args | url | shape ; origin[, once]

``{out}`` in args becomes a fresh per-run output path.  ``once`` runs the
scenario a single time per ref (for trees too big to loop).  A url of ``-``
runs ``ctxd <args>`` with no URL (e.g. ``--version`` for cold start).

Usage::

    uv run scripts/bench.py --ref v0.6.0 --ref HEAD
    uv run scripts/bench.py --only C4,C5 --sweep 1,3,5,8,12
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TARGETS = Path.home() / ".config" / "ctxd" / "bench-targets"
_PROFILE_ROW = re.compile(r"^(\S+)\s+(\d+)\s+([\d.]+)\s*$", re.M)
_SUMMARY = re.compile(r"ctxd summary: (.*)")


@dataclass
class Scenario:
    id: str
    args: list[str]
    url: str
    shape: str
    origin: str
    once: bool


def load_targets(path: Path) -> list[Scenario]:
    scenarios = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        sid, args, url, rest = (part.strip() for part in line.split("|", 3))
        shape, _, origin = rest.partition(";")
        tags = [t.strip() for t in origin.split(",")]
        scenarios.append(Scenario(
            id=sid, args=shlex.split(args), url=url, shape=shape.strip(),
            origin=tags[0], once="once" in tags[1:],
        ))
    return scenarios


def build_ref(ref: str) -> tuple[str, Path]:
    sha = subprocess.check_output(["git", "-C", str(REPO), "rev-parse", ref], text=True).strip()
    prefix = subprocess.check_output(
        ["uvx", "--quiet", "--from", f"ctxd @ git+file://{REPO}@{sha}",
         "python", "-c", "import sys; print(sys.prefix)"],
        text=True,
    ).strip().splitlines()[-1]
    return sha, Path(prefix) / "bin" / "ctxd"


def run_once(binary: Path, sc: Scenario, extra: list[str]) -> dict:
    out_root = Path(tempfile.mkdtemp(prefix=f"ctxd-bench-{sc.id}-"))
    out = out_root / "out"
    args = [a.replace("{out}", str(out)) for a in sc.args]
    cmd = [str(binary), *args, *extra]
    if sc.url != "-":
        cmd = [str(binary), sc.url, *args, "--profile", *extra]
    stdout_path = out_root / "stdout"
    with open(stdout_path, "wb") as so, open(out_root / "stderr", "wb") as se:
        start = time.monotonic()
        proc = subprocess.Popen(cmd, stdout=so, stderr=se)
        _, status, usage = os.wait4(proc.pid, 0)
        wall = time.monotonic() - start
    stderr = (out_root / "stderr").read_text(errors="replace")
    profile = {m.group(1): {"count": int(m.group(2)), "time": float(m.group(3))}
               for m in _PROFILE_ROW.finditer(stderr)}
    written = sum(f.stat().st_size for f in out_root.rglob("*") if f.is_file()
                  and f.name not in ("stderr",))
    summary = _SUMMARY.search(stderr)
    result = {
        "exit": os.waitstatus_to_exitcode(status),
        "wall": round(wall, 3),
        "user": round(usage.ru_utime, 3),
        "sys": round(usage.ru_stime, 3),
        # macOS reports ru_maxrss in bytes, Linux in KiB.
        "maxrss_mb": round(usage.ru_maxrss / (1 << 20 if sys.platform == "darwin" else 1 << 10), 1),
        "bytes": written,
        "http": sum(v["count"] for k, v in profile.items()
                    if k.startswith("http.") and k.count(".") == 1),
        "profile": profile,
        "summary": summary.group(1) if summary else "",
    }
    if result["exit"] != 0:
        result["error"] = stderr.strip().splitlines()[-1][:300] if stderr.strip() else ""
    shutil.rmtree(out_root, ignore_errors=True)
    return result


def environment() -> dict:
    def sh(*cmd: str) -> str:
        try:
            return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            return ""
    return {
        "date": date.today().isoformat(),
        "machine": f"{platform.system()} {platform.release()} {platform.machine()}",
        "python": platform.python_version(),
        "proxy": "netskope" if sh("pgrep", "-i", "netskope") else "none detected",
    }


def stats(values: list[float]) -> dict:
    if not values:
        return {}
    return {
        "median": round(statistics.median(values), 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "stdev": round(statistics.stdev(values), 3) if len(values) > 1 else 0.0,
        "n": len(values),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", action="append", help="git ref to measure (repeatable; default HEAD)")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--warmup", type=int, default=1)
    ap.add_argument("--only", help="comma-separated scenario ids")
    ap.add_argument("--sweep", help="comma-separated --max-concurrency values (first ref only)")
    ap.add_argument("--targets", type=Path, default=TARGETS)
    opts = ap.parse_args()

    refs = opts.ref or ["HEAD"]
    scenarios = load_targets(opts.targets)
    if opts.only:
        wanted = set(opts.only.split(","))
        scenarios = [s for s in scenarios if s.id in wanted]
    builds = {ref: build_ref(ref) for ref in refs}
    head_sha = builds[refs[-1]][0][:7]
    # Raw and summary share one stamp; a sweep gets its own so it cannot
    # overwrite the A/B run of the same day and commit.
    stamp = f"{date.today().isoformat()}-{head_sha}{'-sweep' if opts.sweep else ''}"

    variants: list[tuple[str, list[str]]] = [(ref, []) for ref in refs]
    if opts.sweep:
        variants = [(refs[0], ["--max-concurrency", c]) for c in opts.sweep.split(",")]

    results: dict = {"env": environment(), "refs": {r: b[0] for r, b in builds.items()},
                     "scenarios": {}}
    for sc in scenarios:
        runs = 1 if sc.once else opts.runs
        warmup = 0 if sc.once else opts.warmup
        print(f"[{sc.id}] {sc.shape}  ({runs} run(s) x {len(variants)} variant(s))", flush=True)
        entry = {"shape": sc.shape, "origin": sc.origin, "args": sc.args, "variants": {}}
        for _ in range(warmup):
            for ref, extra in variants:
                run_once(builds[ref][1], sc, extra)
        for i in range(runs):
            for ref, extra in variants:
                key = ref + (f" c={extra[1]}" if extra else "")
                r = run_once(builds[ref][1], sc, extra)
                entry["variants"].setdefault(key, []).append(r)
                flag = "" if r["exit"] == 0 else f"  EXIT {r['exit']}: {r.get('error', '')}"
                print(f"    {key:<16} run {i + 1}: {r['wall']:.2f}s  http={r['http']}{flag}", flush=True)
        results["scenarios"][sc.id] = entry

    raw_dir = REPO / ".bench-out" / stamp
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
    md = render(results, sweep=bool(opts.sweep))
    md_dir = REPO / "bench" / "results"
    md_dir.mkdir(parents=True, exist_ok=True)
    md_path = md_dir / f"{stamp}.md"
    md_path.write_text(md, encoding="utf-8")
    print(f"\nraw: {raw_dir / 'results.json'}\nsummary: {md_path}")
    return 0


def render(results: dict, sweep: bool) -> str:
    env, refs = results["env"], results["refs"]
    lines = [
        f"# ctxd bench — {env['date']}{' (concurrency sweep)' if sweep else ''}",
        "",
        f"- refs: {', '.join(f'`{r}` ({s[:7]})' for r, s in refs.items())}",
        f"- machine: {env['machine']}, Python {env['python']}, proxy: {env['proxy']}",
        "- wall = median of runs (min–max); http = median request count; "
        "bytes = output written; rss = peak resident memory",
        "",
        "| id | shape | variant | wall s | http | bytes | rss MB | user s | exit |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for sid, entry in results["scenarios"].items():
        first = True
        for key, runs in entry["variants"].items():
            ok = [r for r in runs if r["exit"] == 0]
            w = stats([r["wall"] for r in ok])
            wall = f"{w['median']:.2f} ({w['min']:.2f}–{w['max']:.2f})" if w else "—"
            med = lambda f: statistics.median([r[f] for r in ok]) if ok else 0
            fails = len(runs) - len(ok)
            lines.append(
                f"| {sid if first else ''} | {entry['shape'] if first else ''} | {key} | {wall} "
                f"| {med('http'):.0f} | {med('bytes'):,.0f} | {med('maxrss_mb'):.0f} "
                f"| {med('user'):.2f} | {'ok' if not fails else f'{fails} failed'} |"
            )
            first = False
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
