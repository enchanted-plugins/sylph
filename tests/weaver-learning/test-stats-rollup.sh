#!/usr/bin/env bash
# Test: shared/scripts/stats.py correctly rolls up synthetic per-plugin
# metrics.jsonl feeds into a structured JSON summary.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

# ── Sandbox: synthesise a mini Sylph repo layout ─────────────────────
new_sandbox > /dev/null
SBX_PY="$(py_path "$SANDBOX")"

plugins=(
    "boundary-segmenter"
    "branch-workflow"
    "commit-intelligence"
    "sylph-gate"
    "sylph-learning"
    "pr-lifecycle"
    "capability-memory"
)
for p in "${plugins[@]}"; do
    mkdir -p "$SANDBOX/plugins/$p/state"
done

# Boundary-segmenter: 3 boundaries, 1 uncertain, 1 non-boundary event
cat >"$SANDBOX/plugins/boundary-segmenter/state/metrics.jsonl" <<'JSONL'
{"ts":"2026-04-20T10:00:00Z","event":"post_tool_use","boundary":true,"distance":0.40,"uncertain":false,"seg_exit":0,"path":"src/auth.py"}
{"ts":"2026-04-20T10:05:00Z","event":"post_tool_use","boundary":false,"distance":0.12,"uncertain":false,"seg_exit":0,"path":"src/auth.py"}
{"ts":"2026-04-20T10:10:00Z","event":"post_tool_use","boundary":true,"distance":0.55,"uncertain":true,"seg_exit":0,"path":"src/auth.py"}
{"ts":"2026-04-20T10:15:00Z","event":"post_tool_use","boundary":true,"distance":0.48,"uncertain":false,"seg_exit":0,"path":"docs/README.md"}
JSONL

# Branch-workflow: 2 observations (github-flow, trunk)
cat >"$SANDBOX/plugins/branch-workflow/state/metrics.jsonl" <<'JSONL'
{"ts":"2026-04-20T10:01:00Z","event":"w3.boundary.observed","workflow":"github-flow","confidence":0.88}
{"ts":"2026-04-20T10:11:00Z","event":"w3.boundary.observed","workflow":"trunk","confidence":0.71}
JSONL

# Commit-intelligence: 3 drafts — feat × 2, fix × 1
cat >"$SANDBOX/plugins/commit-intelligence/state/metrics.jsonl" <<'JSONL'
{"ts":"2026-04-20T10:02:00Z","event":"w1.boundary.observed","suggested_type":"feat","cluster_event_count":3}
{"ts":"2026-04-20T10:12:00Z","event":"w1.boundary.observed","suggested_type":"feat","cluster_event_count":4}
{"ts":"2026-04-20T10:16:00Z","event":"w1.boundary.observed","suggested_type":"fix","cluster_event_count":2}
JSONL

# Sylph-gate audit: 1 blocked force-push, 1 allowed amend
cat >"$SANDBOX/plugins/sylph-gate/state/audit.jsonl" <<'JSONL'
{"ts":"2026-04-20T10:03:00Z","decision":"blocked","category":"force-push","reason":"protected branch"}
{"ts":"2026-04-20T10:04:00Z","decision":"allowed","category":"amend","reason":"--yes-i-know"}
JSONL

# Pending inboxes — some executed, some not
cat >"$SANDBOX/plugins/branch-workflow/state/pending-actions.jsonl" <<'JSONL'
{"ts":"2026-04-20T10:01:00Z","executed":false,"branch":"feat/a"}
{"ts":"2026-04-20T10:02:00Z","executed":true,"branch":"feat/b"}
{"ts":"2026-04-20T10:03:00Z","executed":false,"branch":"feat/c"}
JSONL

cat >"$SANDBOX/plugins/commit-intelligence/state/pending-drafts.jsonl" <<'JSONL'
{"ts":"2026-04-20T10:02:00Z","executed":false,"subject":"feat: x"}
JSONL

# pr-lifecycle: no pending file at all → must count as 0 without erroring.

# Learnings object
cat >"$SANDBOX/plugins/sylph-learning/state/learnings.json" <<'JSONL'
{"schema_version":"1.0","sample_count":12,"confident":true,"signals":{}}
JSONL

# ── Run stats.py --json --period all against the sandbox ──────────────
out="$("$PY" "$SHARED_SCRIPTS/stats.py" --root "$SBX_PY" --json --period all)"

# Write to a temp file so assert_jq / jq can read it.
tmp="$SANDBOX/rollup.json"
printf '%s' "$out" >"$tmp"

assert_json_valid "$tmp"
assert_jq "$tmp" '.boundaries_detected' "3" "3 boundaries were true"
assert_jq "$tmp" '.boundaries_uncertain' "1" "1 uncertain boundary"
assert_jq "$tmp" '.branches_suggested' "2" "2 branch observations"
assert_jq "$tmp" '.commits_drafted' "3" "3 commits drafted"
assert_jq "$tmp" '.gate_decisions_total' "2" "2 gate decisions logged"
assert_jq "$tmp" '.gate_blocked_categories."force-push"' "1" "1 force-push block"
assert_jq "$tmp" '.pending_actions' "2" "2 pending branch actions"
assert_jq "$tmp" '.pending_drafts' "1" "1 pending commit draft"
assert_jq "$tmp" '.pending_prs' "0" "missing pending-prs → 0"
assert_jq "$tmp" '.commit_types.feat' "2" "feat × 2"
assert_jq "$tmp" '.commit_types.fix' "1" "fix × 1"
assert_jq "$tmp" '.branch_workflows."github-flow"' "1" "github-flow × 1"
assert_jq "$tmp" '.branch_workflows.trunk' "1" "trunk × 1"
assert_jq "$tmp" '.top_file_churn | length > 0 | tostring' "true" "churn list non-empty"
assert_jq "$tmp" '.learning.sample_count' "12" "learning sample count passed through"
ok "stats.py --json rolls up all 4 metric streams + pending inboxes"

# ── Human mode renders without error against same fixture ─────────────
human="$("$PY" "$SHARED_SCRIPTS/stats.py" --root "$SBX_PY" --period all)"
assert_contains "$human" "Boundaries detected:"
assert_contains "$human" "Commits drafted:"
assert_contains "$human" "Pending inbox:"
ok "human-readable mode prints the expected labels"

# ── Missing-files graceful handling ───────────────────────────────────
# Reuse the existing sandbox trap — make a sibling subdir with no plugins.
empty="$SANDBOX/empty-root"
mkdir -p "$empty/plugins"
empty_py="$(py_path "$empty")"
empty_out="$("$PY" "$SHARED_SCRIPTS/stats.py" --root "$empty_py" --json --period all)"
printf '%s' "$empty_out" >"$SANDBOX/empty-rollup.json"
assert_json_valid "$SANDBOX/empty-rollup.json"
assert_jq "$SANDBOX/empty-rollup.json" '.boundaries_detected' "0" "no metrics → 0 boundaries"
assert_jq "$SANDBOX/empty-rollup.json" '.gate_decisions_total' "0" "no audit → 0 gate decisions"
ok "missing plugin files produce zeros rather than errors"
