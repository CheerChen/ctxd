#!/usr/bin/env bash
# Baseline benchmark for ctxd. Runs each scenario N times via `uv run ctxd --profile`
# and prints wall time + profile breakdown per run.
#
# Provide URLs via env vars:
#   CTXD_BENCH_SLACK_URL          Slack thread URL (large, e.g. 50+ replies)
#   CTXD_BENCH_CONF_URL           Confluence page URL (single, will run with -i)
#   CTXD_BENCH_CONF_RECURSIVE_URL Confluence page URL (root of a sub-tree, -r -i)
#   CTXD_BENCH_GITHUB_PR_URL      GitHub PR URL (large, 30+ comments)
#   CTXD_BENCH_RUNS               Repetitions per scenario (default 3)
#
# Optional: set CTXD_BENCH_OUT_DIR (default ./.bench-out). Per-scenario logs land
# under <out>/<scenario>/run-N.log (combined stdout+stderr).
#
# Example:
#   export CTXD_BENCH_SLACK_URL='https://workspace.slack.com/archives/Cxxx/p1234'
#   ./scripts/bench.sh

set -euo pipefail

RUNS="${CTXD_BENCH_RUNS:-3}"
OUT="${CTXD_BENCH_OUT_DIR:-.bench-out}"
mkdir -p "$OUT"

run_scenario() {
  local name="$1"
  shift
  local url="$1"
  shift
  if [[ -z "$url" ]]; then
    echo "[skip] $name — URL not set"
    return
  fi
  local dir="$OUT/$name"
  mkdir -p "$dir"
  echo "──────────────────────────────────────────────────────────────"
  echo "[run] $name  ($RUNS runs)"
  echo "  url:  $url"
  echo "  args: $*"
  echo "──────────────────────────────────────────────────────────────"
  for i in $(seq 1 "$RUNS"); do
    local log="$dir/run-$i.log"
    : > "$log"
    # /usr/bin/time -p prints wall/user/sys; capture both fd into the log.
    { /usr/bin/time -p uv run ctxd --profile "$@" "$url" >/dev/null; } \
      >"$log" 2>&1 || echo "  (run $i failed — see $log)"
    local wall
    wall=$(grep -E "^real " "$log" | awk '{print $2}')
    echo "  run $i  wall=${wall:-?}s   log=$log"
  done
  echo
}

run_scenario "slack"            "${CTXD_BENCH_SLACK_URL:-}"
run_scenario "conf-single-img"  "${CTXD_BENCH_CONF_URL:-}"            -i -o "$OUT/conf-single-img/out"
run_scenario "conf-recursive"   "${CTXD_BENCH_CONF_RECURSIVE_URL:-}"  -r -i -o "$OUT/conf-recursive/out"
run_scenario "github-pr"        "${CTXD_BENCH_GITHUB_PR_URL:-}"

echo "Done. Logs in $OUT/"
echo "Tip: each log has the --profile table at the bottom (after the time line)."
