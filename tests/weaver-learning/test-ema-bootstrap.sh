#!/usr/bin/env bash
# Test: W5 Gauss Learning EMA converges; bootstrap floor suppresses confidence
# below 10 samples; priors export captures the right shape.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

out="$("$PY" - <<PYEOF
import sys, tempfile
from pathlib import Path
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
import gauss_learning as G

td = Path(tempfile.mkdtemp())
sp = td / "learnings.json"

# Feed 20 commits, all with scope → scope_usage_rate should converge near 1.0.
s = G._empty_state()
for _ in range(20):
    s = G.record_commit(s, type_='feat', scope='auth', breaking=False,
                        subject='add thing', body='')
G.save_state(sp, s)

loaded = G.load_state(sp)
p = G.priors(loaded)
print(f"confident={p['confident']}")
print(f"samples={p['sample_count']}")
print(f"scope_rate={p['commit_style']['scope_usage_rate']:.3f}")

# Check bootstrap floor: 5 samples on a fresh state → confident=false.
s2 = G._empty_state()
for _ in range(5):
    s2 = G.record_commit(s2, type_='fix', scope=None, breaking=False,
                         subject='x', body='')
p2 = G.priors(s2)
print(f"low_confident={p2['confident']}")
print(f"low_samples={p2['sample_count']}")

# Confirm persistence roundtrip preserves state exactly.
sp2 = td / "l2.json"
G.save_state(sp2, s2)
reloaded = G.load_state(sp2)
match = reloaded['sample_count'] == s2['sample_count']
print(f"roundtrip_match={match}")
PYEOF
)"

echo "$out" | grep -q '^confident=True$' || fail "20 samples should be confident (got $out)"
echo "$out" | grep -q '^samples=20$' || fail "sample count should be 20"
# scope_rate should be high (close to 1.0) — exact value depends on EMA alpha.
echo "$out" | grep -qE '^scope_rate=0\.9' || fail "scope_rate should be ~0.99 after 20 scoped commits"
echo "$out" | grep -q '^low_confident=False$' || fail "5 samples should NOT be confident"
echo "$out" | grep -q '^low_samples=5$' || fail "low sample count"
echo "$out" | grep -q '^roundtrip_match=True$' || fail "save + load preserves sample_count"
ok "EMA convergence + bootstrap floor + persistence roundtrip"
