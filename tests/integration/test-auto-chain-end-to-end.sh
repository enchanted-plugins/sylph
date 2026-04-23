#!/usr/bin/env bash
# Integration: the auto-orchestration hook chain, end to end.
#
#   PostToolUse(Edit) → boundary-segmenter/boundary-segment.sh (emits on boundary)
#       ├─→ branch-workflow/on-boundary.sh   (writes pending-actions.jsonl)
#       └─→ commit-intelligence/on-boundary.sh (writes pending-drafts.jsonl)
#
# Assertions:
#   1. Three Edit/Write events drive the segmenter to emit one boundary.
#   2. Both downstream hooks advance their listener-offset.json.
#   3. Both downstream hooks append exactly one pending record.
#   4. Re-running downstream hooks with no new events is a no-op (idempotency).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

# Stage a sandbox mirroring the product layout so hooks resolve paths correctly.
new_sandbox >/dev/null
fake_product="$SANDBOX/sylph-sim"
mkdir -p "$fake_product/plugins/boundary-segmenter/hooks/post-tool-use"
mkdir -p "$fake_product/plugins/boundary-segmenter/state"
mkdir -p "$fake_product/plugins/branch-workflow/hooks/post-tool-use"
mkdir -p "$fake_product/plugins/branch-workflow/state"
mkdir -p "$fake_product/plugins/commit-intelligence/hooks/post-tool-use"
mkdir -p "$fake_product/plugins/commit-intelligence/state"

cp "$PLUGINS_ROOT/boundary-segmenter/hooks/post-tool-use/boundary-segment.sh" \
   "$fake_product/plugins/boundary-segmenter/hooks/post-tool-use/"
cp "$PLUGINS_ROOT/branch-workflow/hooks/post-tool-use/on-boundary.sh" \
   "$fake_product/plugins/branch-workflow/hooks/post-tool-use/"
cp "$PLUGINS_ROOT/commit-intelligence/hooks/post-tool-use/on-boundary.sh" \
   "$fake_product/plugins/commit-intelligence/hooks/post-tool-use/"

chmod +x \
    "$fake_product/plugins/boundary-segmenter/hooks/post-tool-use/boundary-segment.sh" \
    "$fake_product/plugins/branch-workflow/hooks/post-tool-use/on-boundary.sh" \
    "$fake_product/plugins/commit-intelligence/hooks/post-tool-use/on-boundary.sh"

# Share the real shared/ tree so Python scripts and atomic_state.sh are found.
ln -s "$REPO_ROOT/shared" "$fake_product/shared"

seg_root="$fake_product/plugins/boundary-segmenter"
bw_root="$fake_product/plugins/branch-workflow"
ci_root="$fake_product/plugins/commit-intelligence"

# Initialize listener offsets (fresh state).
echo '{"last_offset":0}' > "$bw_root/state/listener-offset.json"
echo '{"last_offset":0}' > "$ci_root/state/listener-offset.json"

events="$seg_root/state/boundary-events.jsonl"
bw_offset="$bw_root/state/listener-offset.json"
bw_pending="$bw_root/state/pending-actions.jsonl"
ci_offset="$ci_root/state/listener-offset.json"
ci_pending="$ci_root/state/pending-drafts.jsonl"

# Run the full chain: seg hook, then both listeners.
run_chain() {
    local payload="$1"
    export CLAUDE_PLUGIN_ROOT="$seg_root"
    printf '%s' "$payload" | bash "$seg_root/hooks/post-tool-use/boundary-segment.sh" || true

    export CLAUDE_PLUGIN_ROOT="$bw_root"
    bash "$bw_root/hooks/post-tool-use/on-boundary.sh" 2>/dev/null || true

    export CLAUDE_PLUGIN_ROOT="$ci_root"
    bash "$ci_root/hooks/post-tool-use/on-boundary.sh" 2>/dev/null || true
}

# Event 1: auth edit — opens a cluster, no boundary.
payload_1='{"tool_name":"Edit","tool_input":{"file_path":"src/auth.py","old_string":"old","new_string":"def verify_token(t): return sha256(t)"},"timestamp":1700000000}'
run_chain "$payload_1"

# Event 2: a second auth edit — same cluster, still no boundary.
payload_2='{"tool_name":"Edit","tool_input":{"file_path":"src/auth.py","old_string":"sha256","new_string":"hmac_sha256"},"timestamp":1700000060}'
run_chain "$payload_2"

# Event 3: context switch to docs after a long gap — boundary fires.
payload_3='{"tool_name":"Write","tool_input":{"file_path":"docs/README.md","content":"install package with pip for local development work"},"timestamp":1700000900}'
run_chain "$payload_3"

assert_file_exists "$events" "boundary-events.jsonl should exist after event 3"

# Exactly one boundary line should have been emitted.
boundary_lines=$(grep -c 'sylph.task.boundary.detected' "$events" || true)
assert_eq "$boundary_lines" "1" "exactly one boundary detected across the three events"

# Both listener offsets should have advanced past zero, up to the current file size.
current_size=$(wc -c < "$events" | tr -d '[:space:]')
bw_off=$(jq -r '.last_offset' "$bw_offset")
ci_off=$(jq -r '.last_offset' "$ci_offset")
assert_eq "$bw_off" "$current_size" "branch-workflow offset matches events file size"
assert_eq "$ci_off" "$current_size" "commit-intelligence offset matches events file size"

# Both downstream plugins should have appended exactly one pending record.
assert_file_exists "$bw_pending" "branch-workflow pending-actions.jsonl exists"
assert_file_exists "$ci_pending" "commit-intelligence pending-drafts.jsonl exists"

bw_count=$(wc -l < "$bw_pending" | tr -d '[:space:]')
ci_count=$(wc -l < "$ci_pending" | tr -d '[:space:]')
assert_eq "$bw_count" "1" "branch-workflow wrote one pending-action line"
assert_eq "$ci_count" "1" "commit-intelligence wrote one pending-draft line"

# Record schema sanity.
assert_jq "$bw_pending" '.event' "branch.suggested" "branch-workflow event name"
assert_jq "$bw_pending" '.source_event.event' "sylph.task.boundary.detected" "branch-workflow preserves source event"
assert_jq "$ci_pending" '.event' "commit.drafted" "commit-intelligence event name"
assert_jq "$ci_pending" '.source_event.event' "sylph.task.boundary.detected" "commit-intelligence preserves source event"

ok "hook chain fires end to end: 3 events → 1 boundary → 2 downstream reactions"

# ── Idempotency: re-running the listeners must be a no-op ─────────────
export CLAUDE_PLUGIN_ROOT="$bw_root"
bash "$bw_root/hooks/post-tool-use/on-boundary.sh" 2>/dev/null || true
export CLAUDE_PLUGIN_ROOT="$ci_root"
bash "$ci_root/hooks/post-tool-use/on-boundary.sh" 2>/dev/null || true

bw_count_after=$(wc -l < "$bw_pending" | tr -d '[:space:]')
ci_count_after=$(wc -l < "$ci_pending" | tr -d '[:space:]')
assert_eq "$bw_count_after" "1" "branch-workflow idempotent — no duplicate pending-action"
assert_eq "$ci_count_after" "1" "commit-intelligence idempotent — no duplicate pending-draft"

ok "listeners are idempotent: re-run with no new events emits nothing"
