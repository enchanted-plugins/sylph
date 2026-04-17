#!/usr/bin/env bash
# Test: weaver-learning SessionStart hook exports priors.json + logs status.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

HOOK="$PLUGINS_ROOT/weaver-learning/hooks/session-start/load-priors.sh"
assert_file_exists "$HOOK"

# Sandbox with the product layout so $PRODUCT_ROOT resolves via dir climbing.
new_sandbox > /dev/null
fake_product="$SANDBOX/weaver-sim"
mkdir -p "$fake_product/plugins/weaver-learning/hooks/session-start"
mkdir -p "$fake_product/plugins/weaver-learning/state"
cp "$HOOK" "$fake_product/plugins/weaver-learning/hooks/session-start/load-priors.sh"
chmod +x "$fake_product/plugins/weaver-learning/hooks/session-start/load-priors.sh"
ln -s "$REPO_ROOT/shared" "$fake_product/shared"

fake_plugin_root="$fake_product/plugins/weaver-learning"
state="$fake_plugin_root/state/learnings.json"
priors="$fake_plugin_root/state/priors.json"

# Case 1: no state file yet — hook should produce an empty-state priors file,
# not crash, and log 0 samples.
export CLAUDE_PLUGIN_ROOT="$fake_plugin_root"
set +e
out="$(bash "$fake_plugin_root/hooks/session-start/load-priors.sh" 2>&1)"
rc=$?
set -e
assert_exit_code "0" "$rc" "empty-state exit code"
assert_file_exists "$priors" "priors.json exported"
assert_jq "$priors" '.sample_count' "0" "empty state → 0 samples"
assert_jq "$priors" '.confident' "false" "empty state → confident=false"
assert_contains "$out" "0 samples" "stderr logs 0 samples"
ok "empty state: priors exported, 0 samples, confident=false"

# Case 2: seed state with 12 samples → confident=true.
for i in $(seq 1 12); do
    printf '%s' '{"type":"feat","scope":"x","breaking":false,"subject":"t","body":""}' \
        | "$PY" "$SHARED_SCRIPTS/gauss_learning.py" record-commit "$state" >/dev/null
done

set +e
out="$(bash "$fake_plugin_root/hooks/session-start/load-priors.sh" 2>&1)"
rc=$?
set -e
assert_exit_code "0" "$rc" "seeded exit code"
assert_jq "$priors" '.sample_count' "12" "12 samples recorded"
assert_jq "$priors" '.confident' "true" "12 samples → confident=true"
assert_contains "$out" "12 samples" "stderr logs 12 samples"
assert_contains "$out" "confident=true" "stderr logs confident=true"
ok "seeded state: 12 samples, confident=true"
