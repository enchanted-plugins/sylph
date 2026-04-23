#!/usr/bin/env bash
# Test: 20 parallel append_jsonl invocations must produce exactly 20 lines,
# no truncation, no interleaving. Skipped on Windows — fcntl.flock is a
# POSIX primitive and Sylph's primary target is POSIX.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=./helpers.sh
source "$SCRIPT_DIR/helpers.sh"

# Detect Windows (MSYS, Cygwin, Git-Bash). Ask Python directly — it owns
# the fcntl import and therefore the locking path.
py_os_name="$("$PY" -c 'import os; print(os.name)')"
case "${OSTYPE:-}" in
    msys*|cygwin*|win32*) shell_win=1 ;;
    *) shell_win=0 ;;
esac

if [ "$py_os_name" = "nt" ] || [ "$shell_win" -eq 1 ]; then
    echo "  skip  atomic_state concurrent test: Windows/MSYS (fcntl.flock unavailable)"
    exit 0
fi

new_sandbox > /dev/null
tmp="$SANDBOX"
tmp_py="$(py_path "$tmp")"
target="$tmp/concurrent.jsonl"
target_py="$tmp_py/concurrent.jsonl"
N=20

# Spawn N parallel Python processes, each appending one record under flock.
pids=()
for i in $(seq 1 $N); do
    (
        "$PY" - "$target_py" "$i" "$SHARED_SCRIPTS_PY" <<'PYEOF'
import sys, time
# Light jitter to spread writes across the flock contention window.
time.sleep(0.001 * (int(sys.argv[2]) % 7))
sys.path.insert(0, sys.argv[3])
from atomic_state import append_jsonl
append_jsonl(sys.argv[1], {"seq": int(sys.argv[2]), "payload": "x" * 64})
PYEOF
    ) &
    pids+=($!)
done

# Wait for every writer.
for pid in "${pids[@]}"; do
    wait "$pid"
done

# File must have exactly N lines — no truncation, no lost writes.
lines=$(wc -l < "$target")
assert_eq "$lines" "$N" "concurrent append: line count"

# Every line must be valid JSON, payload must not be truncated, each seq
# must appear exactly once.
"$PY" - "$target_py" "$N" <<'PYEOF'
import json, sys
from collections import Counter
path, n = sys.argv[1], int(sys.argv[2])
seen = Counter()
with open(path, "r", encoding="utf-8") as f:
    for lineno, line in enumerate(f, 1):
        line = line.rstrip("\n")
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"FAIL line {lineno}: invalid JSON ({e}): {line!r}")
            sys.exit(1)
        if len(rec.get("payload", "")) != 64:
            print(f"FAIL line {lineno}: truncated payload: {rec!r}")
            sys.exit(1)
        seen[rec["seq"]] += 1
expected = set(range(1, n + 1))
got = set(seen.keys())
if got != expected:
    print(f"FAIL missing/extra seqs. missing={expected - got}, extra={got - expected}")
    sys.exit(1)
dupes = [s for s, c in seen.items() if c != 1]
if dupes:
    print(f"FAIL duplicate seqs: {dupes}")
    sys.exit(1)
PYEOF

ok "concurrent: 20 parallel appends -> 20 valid lines, no corruption, no dupes"
