#!/usr/bin/env bash
# Test: atomic_json.py roundtrip — write, read, append_jsonl, iter_jsonl.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=./helpers.sh
source "$SCRIPT_DIR/helpers.sh"

new_sandbox > /dev/null
tmp="$SANDBOX"

# atomic_write_json + read_json roundtrip.
out="$("$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from pathlib import Path
from atomic_json import atomic_write_json, read_json
p = Path(r"$tmp") / "obj.json"
atomic_write_json(p, {"a": 1, "b": [2, 3]})
got = read_json(p)
print("ok" if got == {"a": 1, "b": [2, 3]} else "fail")
PYEOF
)"
assert_eq "$out" "ok" "atomic_write/read roundtrip"
ok "atomic_write_json + read_json roundtrip"

# append_jsonl + iter_jsonl with malformed line in the middle.
out="$("$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from pathlib import Path
from atomic_json import append_jsonl, iter_jsonl
p = Path(r"$tmp") / "log.jsonl"
append_jsonl(p, {"n": 1})
# Inject a malformed line.
with open(p, "a", encoding="utf-8") as f:
    f.write("NOT JSON\n")
append_jsonl(p, {"n": 2})
recs = list(iter_jsonl(p))
print("ok" if recs == [{"n": 1}, {"n": 2}] else f"fail: {recs}")
PYEOF
)"
assert_eq "$out" "ok" "append_jsonl + iter_jsonl tolerates malformed lines"
ok "append_jsonl + iter_jsonl (skips malformed)"

# read_json on missing file returns default.
out="$("$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from atomic_json import read_json
print(read_json(r"$tmp/nonexistent.json", default="MISSING"))
PYEOF
)"
assert_eq "$out" "MISSING" "read_json default on missing file"
ok "read_json returns default on missing file"
