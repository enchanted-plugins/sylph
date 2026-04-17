#!/usr/bin/env bash
# Integration: simulate the full auto-orchestration chain.
#   1. An Edit event fires PostToolUse.
#   2. Another Edit on a different file after a long gap → W2 boundary fires.
#   3. The closed cluster + commits build a PR description.
#   4. Reviewer ranking picks the last committer on the affected files.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

# Mini repo with two authors.
dir="$(mktemp -d)"
dir_py="$(py_path "$dir")"
cd "$dir"
git init -q -b main

git config user.email alice@test.com
git config user.name alice
mkdir -p src docs
echo "alpha" > src/auth.py
git add . && git commit -q -m "feat: initial auth"

git config user.email bob@test.com
git config user.name bob
echo "beta" > src/auth.py
git add . && git commit -q -m "fix: auth edge"

# Step 1 + 2: drive W2 via Python end-to-end.
out="$("$PY" - <<PYEOF
import sys, os
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from boundary_segment import Segmenter, Event, vector_from_text
from pr_lifecycle import PRDescription
import reviewer_route as R
from pathlib import Path

seg = Segmenter()

# Cluster A: two edits on auth.py, similar tokens, 1-minute apart.
seg.step(Event(1000.0, 'Edit', {'src/auth.py'}, vector_from_text('def verify_token return sha256')))
seg.step(Event(1060.0, 'Edit', {'src/auth.py'}, vector_from_text('def verify_token return hmac')))

# Context switch: docs edit after 25-minute gap → boundary.
r = seg.step(Event(2600.0, 'Write', {'docs/README.md'},
                   vector_from_text('install package via pip for local development')))

print(f"boundary={r.boundary_fired}")
print(f"distance={r.distance:.3f}")
print(f"closed_files={sorted({f for e in seg.closed_clusters[-1].events for f in e.files})}")

# Step 3: compose PR description from the closed cluster + a fake commit.
desc = PRDescription.from_cluster(
    cluster=seg.closed_clusters[-1].to_json(),
    commits=[{"sha": "abcdef1234", "subject": "feat(auth): harden token verify", "author": "alice"}],
    session_continuity=None,
)
print(f"title_ok={'feat(auth)' in desc.title}")
print(f"body_has_what_changed={'What changed' in desc.body}")
print(f"body_has_rollback={'git revert --no-commit abcdef12' in desc.body}")

# Step 4: reviewer ranking on the changed file.
ranked = R.suggest(["src/auth.py"], Path(r"$dir_py"), max_suggest=3)
print(f"reviewer_count={len(ranked)}")
identities = [c['identity'] for c in ranked]
print(f"alice_in_ranking={any('alice' in i for i in identities)}")
print(f"bob_in_ranking={any('bob' in i for i in identities)}")
PYEOF
)"

echo "$out"
echo "$out" | grep -q '^boundary=True$' || fail "integration: boundary should fire on context switch"
echo "$out" | grep -q "^closed_files=\['src/auth.py'\]\$" || fail "closed cluster should reference src/auth.py"
echo "$out" | grep -q '^title_ok=True$' || fail "PR title should use commit subject"
echo "$out" | grep -q '^body_has_what_changed=True$' || fail "PR body should include What changed section"
echo "$out" | grep -q '^body_has_rollback=True$' || fail "PR body should include rollback command"
# At least one of alice/bob should be in the ranking — they are the only two authors on auth.py.
echo "$out" | grep -qE '^(alice_in_ranking=True|bob_in_ranking=True)$' || fail "one of alice/bob should rank"
ok "edit → W2 boundary → PR description → reviewer ranking end to end"

rm -rf "$dir"
