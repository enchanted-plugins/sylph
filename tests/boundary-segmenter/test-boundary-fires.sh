#!/usr/bin/env bash
# Test: context-switching events (different file, different tokens, long idle)
# fire a boundary as expected.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

out="$("$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from boundary_segment import Segmenter, Event, vector_from_text

seg = Segmenter()
# First cluster: auth edits.
for t in [1000.0, 1030.0]:
    seg.step(Event(t, 'Edit', {'src/auth.py'}, vector_from_text('def verify_token hash sha256')))

# Context switch: docs file, very different tokens, 20-minute gap.
r = seg.step(Event(2200.0, 'Write', {'docs/README.md'},
                   vector_from_text('install package with pip for local development')))

print(f'boundary={r.boundary_fired}')
print(f'distance={r.distance:.3f}')
print(f'closed={len(seg.closed_clusters)}')

# The closed cluster should have the first two auth events.
closed = seg.closed_clusters[-1]
print(f'closed_events={len(closed.events)}')
files = sorted({f for e in closed.events for f in e.files})
print(f'closed_files={files}')
PYEOF
)"

echo "$out" | grep -q '^boundary=True$' || fail "context switch should fire boundary (got: $out)"
echo "$out" | grep -q '^closed=1$' || fail "exactly one cluster should have closed"
echo "$out" | grep -q '^closed_events=2$' || fail "closed cluster should hold both auth events"
echo "$out" | grep -q "'src/auth.py'" || fail "closed cluster should reference src/auth.py"
ok "context switch fires boundary, closed cluster preserved"
