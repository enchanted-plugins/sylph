#!/usr/bin/env bash
# Test: PRDescription.from_cluster composes the 4-section body with + without
# Hornet V4 session-continuity, and falls back gracefully when missing.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

# Case 1: with commits but no V4 continuity — must fall back with a note.
out="$("$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from pr_lifecycle import PRDescription

cluster = {"events": [{"files": ["src/auth.py"], "vector": {"pkce": 0.7}}]}
commits = [{"sha": "abc1234567", "subject": "feat(auth): add OAuth PKCE", "author": "dev"}]
desc = PRDescription.from_cluster(cluster=cluster, commits=commits, session_continuity=None)
print("TITLE:" + desc.title)
print("---")
print(desc.body)
PYEOF
)"

assert_contains "$out" "TITLE:feat(auth): add OAuth PKCE" "title uses commit subject"
assert_contains "$out" "## What changed" "What changed section present"
assert_contains "$out" "## Why" "Why section present"
assert_contains "$out" "## How it was verified" "verification section present"
assert_contains "$out" "## Rollback plan" "rollback section present"
assert_contains "$out" "Hornet V4 session-continuity data unavailable" "V4 fallback note present"
assert_contains "$out" "abc12345" "short sha (8 chars) in body"
assert_contains "$out" "git revert --no-commit abc12345" "rollback command cites the sha"
assert_contains "$out" "Opened by [Weaver]" "attribution footer"
ok "without V4: 4 sections rendered, fallback note present, rollback complete"

# Case 2: with V4 continuity — Why section pulls from decisions.
out="$("$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from pr_lifecycle import PRDescription

cluster = {"events": [{"files": ["src/auth.py"], "vector": {"pkce": 0.7}}]}
commits = [{"sha": "abc1234567", "subject": "feat(auth): add OAuth PKCE", "author": "dev"}]
continuity = {
    "decisions": [
        "Chose PKCE over client-secret for the mobile flow",
        "Selected sha256 over sha1 to match spec",
    ],
    "verified": [
        "pytest tests/auth/ passed",
        "integration run against staging green",
    ],
}
desc = PRDescription.from_cluster(cluster=cluster, commits=commits, session_continuity=continuity)
print(desc.body)
PYEOF
)"

assert_contains "$out" "Chose PKCE over client-secret" "Why section pulls V4 decision 1"
assert_contains "$out" "Selected sha256 over sha1" "Why section pulls V4 decision 2"
assert_contains "$out" "pytest tests/auth/ passed" "Verified section pulls V4 verified 1"
assert_not_contains "$out" "Hornet V4 session-continuity data unavailable" "no fallback note when V4 present"
ok "with V4: Why + Verified pull from continuity graph"

# Case 3: no commits and no cluster — still produces a non-crash body.
out="$("$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from pr_lifecycle import PRDescription

desc = PRDescription.from_cluster(cluster=None, commits=[], session_continuity=None)
print("TITLE:" + desc.title)
print(desc.body[:200])
PYEOF
)"
assert_contains "$out" "chore: weaver-drafted PR" "fallback title when empty"
ok "empty inputs: default title, degrades gracefully"
