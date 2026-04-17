#!/usr/bin/env bash
# Test: all four record-* signal kinds (commit, branch, reviewer, w2-correction)
# move the expected fields in the persisted state.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

new_sandbox > /dev/null
sp="$SANDBOX/learnings.json"

# record-commit via CLI (stdin JSON).
printf '%s' '{"type":"feat","scope":"auth","breaking":false,"subject":"add pkce","body":"details"}' \
    | "$PY" "$SHARED_SCRIPTS/gauss_learning.py" record-commit "$sp" >/dev/null

# record-branch
"$PY" "$SHARED_SCRIPTS/gauss_learning.py" record-branch "$sp" "feat/add-oauth-pkce" >/dev/null

# record-reviewer
"$PY" "$SHARED_SCRIPTS/gauss_learning.py" record-reviewer "$sp" "tech-lead" "added" >/dev/null

# record-w2-correction
"$PY" "$SHARED_SCRIPTS/gauss_learning.py" record-w2-correction "$sp" "merge" >/dev/null

# Dump + inspect.
dump="$("$PY" "$SHARED_SCRIPTS/gauss_learning.py" dump "$sp")"

assert_jq "$sp" '.sample_count' "1" "sample_count after one commit"
assert_jq "$sp" '.commit_style.scope_usage_rate > 0 | tostring' "true" "scope_usage_rate > 0"
assert_jq "$sp" '.commit_style.top_scopes.auth > 0 | tostring' "true" "top_scopes.auth > 0"
assert_jq "$sp" '.branch_naming.slug_style' "kebab" "slug_style = kebab"
assert_jq "$sp" '.branch_naming.type_prefix_rate > 0 | tostring' "true" "type_prefix_rate > 0"
assert_jq "$sp" '.reviewer_overrides."tech-lead" > 0 | tostring' "true" "tech-lead override weight > 0"
assert_jq "$sp" '.w2_corrections.false_split' "1" "false_split recorded"
assert_jq "$sp" '.w2_corrections.boundary_overrides' "1" "boundary_overrides counter"
ok "all 4 record-* signals mutate the expected state fields"

# record-reviewer "removed" produces negative weight.
"$PY" "$SHARED_SCRIPTS/gauss_learning.py" record-reviewer "$sp" "wrong-person" "removed" >/dev/null
actual="$(jq -r '.reviewer_overrides."wrong-person"' "$sp")"
# Expected: negative (signal was -1.0, prior 0.0, alpha 0.3 → -0.3)
case "$actual" in
    -*) ok "'removed' reviewer → negative weight" ;;
    *) fail "'removed' should produce negative weight (got $actual)" ;;
esac
