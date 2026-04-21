#!/usr/bin/env bash
# Integration: the FULL auto-orchestration chain, end to end.
#
#   PostToolUse(Edit) → boundary-segmenter/boundary-segment.sh
#       ├─→ branch-workflow/on-boundary.sh       (→ pending-actions.jsonl)
#       └─→ commit-intelligence/on-boundary.sh   (→ pending-drafts.jsonl)
#                                                     │
#                                    (Agent 1: /weaver:commit executes the
#                                     commit + appends to executed-commits.jsonl
#                                     — simulated here by writing the feed
#                                     directly, matching the Agent-1 contract)
#                                                     │
#   PostToolUse(Bash)  → pr-lifecycle/on-commit.sh    (→ pending-prs.jsonl)
#
# This test asserts the full propagation:
#   1. Three Edit/Write events → one boundary.
#   2. Both boundary-listeners (branch-workflow, commit-intelligence) fire.
#   3. A simulated executed-commit record (the Agent-1 contract) is written
#      to commit-intelligence/state/executed-commits.jsonl.
#   4. pr-lifecycle/on-commit.sh picks it up and writes a PR draft.
#   5. All four downstream state files have exactly one new record each.
#   6. All four listener-offsets have advanced past zero.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

# Stage a sandbox mirroring the product layout.
new_sandbox >/dev/null
fake_product="$SANDBOX/weaver-sim"
mkdir -p "$fake_product/plugins/boundary-segmenter/hooks/post-tool-use"
mkdir -p "$fake_product/plugins/boundary-segmenter/state"
mkdir -p "$fake_product/plugins/branch-workflow/hooks/post-tool-use"
mkdir -p "$fake_product/plugins/branch-workflow/state"
mkdir -p "$fake_product/plugins/commit-intelligence/hooks/post-tool-use"
mkdir -p "$fake_product/plugins/commit-intelligence/state"
mkdir -p "$fake_product/plugins/pr-lifecycle/hooks/post-tool-use"
mkdir -p "$fake_product/plugins/pr-lifecycle/state"

cp "$PLUGINS_ROOT/boundary-segmenter/hooks/post-tool-use/boundary-segment.sh" \
   "$fake_product/plugins/boundary-segmenter/hooks/post-tool-use/"
cp "$PLUGINS_ROOT/branch-workflow/hooks/post-tool-use/on-boundary.sh" \
   "$fake_product/plugins/branch-workflow/hooks/post-tool-use/"
cp "$PLUGINS_ROOT/commit-intelligence/hooks/post-tool-use/on-boundary.sh" \
   "$fake_product/plugins/commit-intelligence/hooks/post-tool-use/"
cp "$PLUGINS_ROOT/pr-lifecycle/hooks/post-tool-use/on-commit.sh" \
   "$fake_product/plugins/pr-lifecycle/hooks/post-tool-use/"

# Share the real shared/ tree so Python + atomic_state.sh are found.
ln -s "$REPO_ROOT/shared" "$fake_product/shared"

seg_root="$fake_product/plugins/boundary-segmenter"
bw_root="$fake_product/plugins/branch-workflow"
ci_root="$fake_product/plugins/commit-intelligence"
pr_root="$fake_product/plugins/pr-lifecycle"

# Initialize listener offsets (fresh state).
echo '{"last_offset":0}' > "$bw_root/state/listener-offset.json"
echo '{"last_offset":0}' > "$ci_root/state/listener-offset.json"
echo '{"last_offset":0}' > "$pr_root/state/listener-offset.json"

events="$seg_root/state/boundary-events.jsonl"
bw_pending="$bw_root/state/pending-actions.jsonl"
ci_pending="$ci_root/state/pending-drafts.jsonl"
executed_commits="$ci_root/state/executed-commits.jsonl"
pr_pending="$pr_root/state/pending-prs.jsonl"

bw_offset="$bw_root/state/listener-offset.json"
ci_offset="$ci_root/state/listener-offset.json"
pr_offset="$pr_root/state/listener-offset.json"

# ── Phase 1: Edits → boundary → branch + commit drafts ─────────────────
run_upstream() {
    local payload="$1"
    export CLAUDE_PLUGIN_ROOT="$seg_root"
    printf '%s' "$payload" | bash "$seg_root/hooks/post-tool-use/boundary-segment.sh" || true

    export CLAUDE_PLUGIN_ROOT="$bw_root"
    bash "$bw_root/hooks/post-tool-use/on-boundary.sh" 2>/dev/null || true

    export CLAUDE_PLUGIN_ROOT="$ci_root"
    bash "$ci_root/hooks/post-tool-use/on-boundary.sh" 2>/dev/null || true
}

payload_1='{"tool_name":"Edit","tool_input":{"file_path":"src/auth.py","old_string":"old","new_string":"def verify_token(t): return sha256(t)"},"timestamp":1700000000}'
run_upstream "$payload_1"

payload_2='{"tool_name":"Edit","tool_input":{"file_path":"src/auth.py","old_string":"sha256","new_string":"hmac_sha256"},"timestamp":1700000060}'
run_upstream "$payload_2"

payload_3='{"tool_name":"Write","tool_input":{"file_path":"docs/README.md","content":"install package with pip for local development work"},"timestamp":1700000900}'
run_upstream "$payload_3"

assert_file_exists "$events" "boundary-events.jsonl should exist after event 3"

boundary_lines=$(grep -c 'weaver.task.boundary.detected' "$events" || true)
assert_eq "$boundary_lines" "1" "exactly one boundary detected across the three edits"

# Branch + commit listeners reacted.
assert_file_exists "$bw_pending" "branch-workflow pending-actions.jsonl exists"
assert_file_exists "$ci_pending" "commit-intelligence pending-drafts.jsonl exists"
assert_eq "$(wc -l < "$bw_pending" | tr -d '[:space:]')" "1" "branch-workflow wrote one pending-action"
assert_eq "$(wc -l < "$ci_pending" | tr -d '[:space:]')" "1" "commit-intelligence wrote one pending-draft"

# Offsets advanced past zero.
bw_off=$(jq -r '.last_offset' "$bw_offset")
ci_off=$(jq -r '.last_offset' "$ci_offset")
[[ "$bw_off" -gt 0 ]] || fail "branch-workflow offset did not advance"
[[ "$ci_off" -gt 0 ]] || fail "commit-intelligence offset did not advance"
ok "Phase 1: 3 edits → 1 boundary → 2 upstream listeners reacted"

# ── Phase 2: Agent-1 contract — /weaver:commit appends to executed-commits.jsonl ──
# Simulate the contract Agent 1 is wiring: on successful `git commit`,
# /weaver:commit appends a `weaver.commit.committed` record to
# plugins/commit-intelligence/state/executed-commits.jsonl and flips the
# matching pending-drafts record to executed:true. This test focuses on the
# event-file side (pr-lifecycle only cares about that).
pending_draft_ts="$(jq -r '.ts' "$ci_pending")"
commit_message="$(jq -r '"\(.suggested_type)(auth): harden token verify"' "$ci_pending")"

executed_ts="2026-04-20T10:00:00Z"
jq -nc \
    --arg ts "$executed_ts" \
    --arg event "weaver.commit.committed" \
    --arg sha "abcdef1234567890feedface" \
    --arg branch "feat/verify-token" \
    --arg message "$commit_message" \
    --arg source_draft_ts "$pending_draft_ts" \
    '{ts:$ts, event:$event, sha:$sha, branch:$branch, message:$message, source_draft_ts:$source_draft_ts}' \
    >> "$executed_commits"

assert_file_exists "$executed_commits" "executed-commits.jsonl seeded per Agent-1 contract"
assert_eq "$(wc -l < "$executed_commits" | tr -d '[:space:]')" "1" "exactly one executed-commit record"
ok "Phase 2: Agent-1 contract — executed-commits.jsonl appended on successful commit"

# ── Phase 3: pr-lifecycle listener closes the chain ─────────────────────
export CLAUDE_PLUGIN_ROOT="$pr_root"
bash "$pr_root/hooks/post-tool-use/on-commit.sh" 2>/dev/null || true

assert_file_exists "$pr_pending" "pr-lifecycle pending-prs.jsonl exists after on-commit"
assert_eq "$(wc -l < "$pr_pending" | tr -d '[:space:]')" "1" "pr-lifecycle wrote one pending-pr"

# Offset advanced.
pr_off=$(jq -r '.last_offset' "$pr_offset")
[[ "$pr_off" -gt 0 ]] || fail "pr-lifecycle offset did not advance"

# Record schema end-to-end.
assert_jq "$pr_pending" '.event' "weaver.pr.drafted" "pr-lifecycle event name"
assert_jq "$pr_pending" '.branch' "feat/verify-token" "pr-lifecycle carries branch through"
assert_jq "$pr_pending" '.sha' "abcdef1234567890feedface" "pr-lifecycle carries sha through"
assert_jq "$pr_pending" '.source_event.event' "weaver.commit.committed" "pr-lifecycle preserves source event"
assert_jq "$pr_pending" '.source_draft_ts' "$pending_draft_ts" "pr-lifecycle carries source_draft_ts (links back to commit-intelligence record)"
ok "Phase 3: executed-commit event → PR draft record"

# ── Phase 4: idempotency across the full chain ──────────────────────────
# Re-run every listener; nothing should change.
export CLAUDE_PLUGIN_ROOT="$bw_root"
bash "$bw_root/hooks/post-tool-use/on-boundary.sh" 2>/dev/null || true
export CLAUDE_PLUGIN_ROOT="$ci_root"
bash "$ci_root/hooks/post-tool-use/on-boundary.sh" 2>/dev/null || true
export CLAUDE_PLUGIN_ROOT="$pr_root"
bash "$pr_root/hooks/post-tool-use/on-commit.sh" 2>/dev/null || true

assert_eq "$(wc -l < "$bw_pending" | tr -d '[:space:]')" "1" "branch-workflow idempotent on re-run"
assert_eq "$(wc -l < "$ci_pending" | tr -d '[:space:]')" "1" "commit-intelligence idempotent on re-run"
assert_eq "$(wc -l < "$pr_pending" | tr -d '[:space:]')" "1" "pr-lifecycle idempotent on re-run"
ok "Phase 4: every listener is idempotent — re-run propagates nothing new"

ok "FULL CHAIN: edit → boundary → branch + commit drafts → committed → PR drafted"
