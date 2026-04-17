#!/usr/bin/env bash
# Test: a stream of edits on the same file with similar tokens stays in one
# cluster (no boundary fires).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

out="$("$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from boundary_segment import Segmenter, Event, vector_from_text

seg = Segmenter()
# Three edits on the same file, similar tokens, 30 seconds apart each.
events = [
    Event(1000.0, 'Edit', {'src/auth.py'}, vector_from_text('def verify_token(t): return hash(t)')),
    Event(1030.0, 'Edit', {'src/auth.py'}, vector_from_text('def verify_token(t): return sha256(t)')),
    Event(1060.0, 'Edit', {'src/auth.py'}, vector_from_text('def verify_token(t): return hmac(t)')),
]
boundaries = 0
for e in events:
    r = seg.step(e)
    if r.boundary_fired:
        boundaries += 1

print(f'boundaries={boundaries}')
print(f'active_size={len(seg.active.events)}')
print(f'closed={len(seg.closed_clusters)}')
PYEOF
)"

echo "$out" | grep -q '^boundaries=0$' || fail "cohesive stream should not fire a boundary (got: $out)"
echo "$out" | grep -q '^active_size=3$' || fail "all 3 events should be in one cluster"
echo "$out" | grep -q '^closed=0$' || fail "no clusters should have closed"
ok "cohesive stream: 0 boundaries, 1 cluster with 3 events"
