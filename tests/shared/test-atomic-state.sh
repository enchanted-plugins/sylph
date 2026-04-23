#!/usr/bin/env bash
# Test: shared/scripts/atomic_state.{py,sh} contract end-to-end.
#
# Exercises every public entry point agents D (hook wiring) and E
# (safe-amend) call against:
#   read_state / write_state / append_jsonl  (Python)
#   atomic_read / atomic_write / atomic_append  (bash wrapper)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=./helpers.sh
source "$SCRIPT_DIR/helpers.sh"

# shellcheck source=../../shared/scripts/atomic_state.sh
source "$REPO_ROOT/shared/scripts/atomic_state.sh"

new_sandbox > /dev/null
tmp="$SANDBOX"
tmp_py="$(py_path "$tmp")"

# ── Python API ────────────────────────────────────────────────────────

# write_state + read_state roundtrip, exact schema match.
out="$("$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from pathlib import Path
from atomic_state import read_state, write_state
p = Path(r"$tmp_py") / "state.json"
write_state(p, {"schema_version": "1.0", "clusters": [{"id": "c1"}], "last_compacted": None})
got = read_state(p)
ok = (
    got == {"schema_version": "1.0", "clusters": [{"id": "c1"}], "last_compacted": None}
    and p.read_text(encoding="utf-8").endswith("\n")
    and "  " in p.read_text(encoding="utf-8")  # 2-space indent
)
print("ok" if ok else "fail")
PYEOF
)"
assert_eq "$out" "ok" "write_state/read_state roundtrip + trailing newline + indent"
ok "Python: write_state + read_state roundtrip (trailing \\n, 2-space indent)"

# read_state default on missing file.
out="$("$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from atomic_state import read_state
print(read_state(r"$tmp_py/does-not-exist.json", default="SENTINEL"))
PYEOF
)"
assert_eq "$out" "SENTINEL" "read_state on missing returns default"
ok "Python: read_state returns default on missing file"

# read_state default when default is None -> {}.
out="$("$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from atomic_state import read_state
r = read_state(r"$tmp_py/also-missing.json")
print("empty-dict" if r == {} else f"wrong: {r!r}")
PYEOF
)"
assert_eq "$out" "empty-dict" "read_state default None -> {}"
ok "Python: read_state default=None returns {} on missing file"

# read_state tolerates corrupt JSON.
printf '%s' '{"broken": ' > "$tmp/corrupt.json"
out="$("$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from atomic_state import read_state
print(read_state(r"$tmp_py/corrupt.json", default="FALLBACK"))
PYEOF
)"
assert_eq "$out" "FALLBACK" "read_state tolerates corrupt JSON"
ok "Python: read_state returns default on corrupt JSON"

# read_state on empty file returns default.
: > "$tmp/empty.json"
out="$("$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from atomic_state import read_state
print(read_state(r"$tmp_py/empty.json", default="EMPTY"))
PYEOF
)"
assert_eq "$out" "EMPTY" "read_state empty file returns default"
ok "Python: read_state returns default on empty file"

# append_jsonl produces valid line-delimited JSON.
out="$("$PY" - <<PYEOF
import sys, json
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from pathlib import Path
from atomic_state import append_jsonl
p = Path(r"$tmp_py") / "audit.jsonl"
for i in range(5):
    append_jsonl(p, {"event": "sylph.test", "seq": i})
lines = p.read_text(encoding="utf-8").splitlines()
recs = [json.loads(l) for l in lines]
ok = len(recs) == 5 and all(r["seq"] == i for i, r in enumerate(recs))
print("ok" if ok else "fail")
PYEOF
)"
assert_eq "$out" "ok" "append_jsonl line-delimited JSON"
ok "Python: append_jsonl produces valid line-delimited JSON"

# append_jsonl creates parent dirs.
out="$("$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from pathlib import Path
from atomic_state import append_jsonl
p = Path(r"$tmp_py") / "deep" / "nested" / "log.jsonl"
append_jsonl(p, {"event": "sylph.test"})
print("ok" if p.exists() else "fail")
PYEOF
)"
assert_eq "$out" "ok" "append_jsonl creates parent dirs"
ok "Python: append_jsonl creates missing parent directories"

# write_state creates parent dirs.
out="$("$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from pathlib import Path
from atomic_state import write_state
p = Path(r"$tmp_py") / "another" / "deep" / "s.json"
write_state(p, {"k": "v"})
print("ok" if p.exists() else "fail")
PYEOF
)"
assert_eq "$out" "ok" "write_state creates parent dirs"
ok "Python: write_state creates missing parent directories"

# ── Bash wrapper ──────────────────────────────────────────────────────

# atomic_read on missing file echoes {}.
out="$(atomic_read "$tmp/missing-bash.json")"
assert_eq "$out" "{}" "atomic_read missing file"
ok "bash: atomic_read echoes {} on missing file"

# atomic_write + atomic_read roundtrip.
printf '%s' '{"hello":"world"}' | atomic_write "$tmp/hello.json"
out="$(atomic_read "$tmp/hello.json")"
assert_contains "$out" '"hello":"world"' "atomic_write roundtrip"
assert_json_valid "$tmp/hello.json" "atomic_write produced valid JSON"
ok "bash: atomic_write + atomic_read roundtrip"

# atomic_write creates parent dirs.
printf '%s' '{"k":1}' | atomic_write "$tmp/new/dir/s.json"
assert_file_exists "$tmp/new/dir/s.json" "atomic_write created parent dir"
ok "bash: atomic_write creates missing parent dirs"

# atomic_append produces JSONL.
printf '%s' '{"event":"a"}' | atomic_append "$tmp/log.jsonl"
printf '%s' '{"event":"b"}' | atomic_append "$tmp/log.jsonl"
lines=$(wc -l < "$tmp/log.jsonl")
assert_eq "$lines" "2" "atomic_append line count"
# Each line must be valid JSON.
while IFS= read -r line; do
    printf '%s' "$line" | jq empty >/dev/null 2>&1 || fail "atomic_append produced invalid JSON line: $line"
done < "$tmp/log.jsonl"
ok "bash: atomic_append produces valid JSONL (2 records)"

# atomic_append creates parent dirs.
printf '%s' '{"event":"c"}' | atomic_append "$tmp/nested/log/more.jsonl"
assert_file_exists "$tmp/nested/log/more.jsonl" "atomic_append created parent dir"
ok "bash: atomic_append creates missing parent dirs"

# Cross-language: bash writes, Python reads — and vice versa.
printf '%s' '{"from":"bash","n":42}' | atomic_write "$tmp/cross.json"
out="$("$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from atomic_state import read_state
r = read_state(r"$tmp_py/cross.json")
print("ok" if r == {"from": "bash", "n": 42} else f"fail: {r!r}")
PYEOF
)"
assert_eq "$out" "ok" "python reads bash-written state"
ok "cross-lang: Python read_state reads bash-written JSON"

"$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from atomic_state import write_state
write_state(r"$tmp_py/from-py.json", {"from": "py", "list": [1, 2, 3]})
PYEOF
out="$(atomic_read "$tmp/from-py.json" | jq -c .)"
assert_eq "$out" '{"from":"py","list":[1,2,3]}' "bash reads python-written state"
ok "cross-lang: bash atomic_read reads Python-written JSON"
