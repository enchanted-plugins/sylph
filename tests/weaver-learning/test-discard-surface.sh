#!/usr/bin/env bash
# Test: /sylph:discard surface + pending_inbox.py discard CLI.
#
# Coverage:
#   1. mark_discarded on middle record: file still has N lines, exactly one
#      carries discarded:true.
#   2. read_pending now returns N-1 records (discarded ones excluded).
#   3. grep "discarded":true" finds exactly one line (per seed inbox).
#   4. Re-discarding the same ts is a no-op, exit 0, file unchanged count.
#   5. Unknown ts exits non-zero with a stderr message.
#   6. discard_surface.py list aggregates all 3 inboxes and filters.
#   7. discard_surface.py resolve maps (inbox, index) → (path, ts) correctly.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

INBOX="$SHARED_SCRIPTS/pending_inbox.py"
SURFACE="$SHARED_SCRIPTS/discard_surface.py"
assert_file_exists "$INBOX" "pending_inbox.py missing"
assert_file_exists "$SURFACE" "discard_surface.py missing"

new_sandbox > /dev/null
SBX_PY="$(py_path "$SANDBOX")"

# ── Seed three inbox fixtures ─────────────────────────────────────────
mkdir -p "$SANDBOX/plugins/branch-workflow/state"
mkdir -p "$SANDBOX/plugins/commit-intelligence/state"
mkdir -p "$SANDBOX/plugins/pr-lifecycle/state"

branch_path="$SANDBOX/plugins/branch-workflow/state/pending-actions.jsonl"
commit_path="$SANDBOX/plugins/commit-intelligence/state/pending-drafts.jsonl"
pr_path="$SANDBOX/plugins/pr-lifecycle/state/pending-prs.jsonl"

# Branch inbox — 3 records, middle one will be discarded by ts.
cat > "$branch_path" <<'EOF'
{"ts":"2026-04-20T10:00:00Z","event":"branch.suggested","workflow":"github-flow","dominant_file":"src/auth.py","confidence":0.9,"executed":false}
{"ts":"2026-04-20T10:05:00Z","event":"branch.suggested","workflow":"trunk","dominant_file":"README.md","confidence":0.5,"executed":false}
{"ts":"2026-04-20T10:10:00Z","event":"branch.suggested","workflow":"gitflow","dominant_file":"src/api.py","confidence":0.75,"executed":false}
EOF

# Commit inbox — 1 pending + 1 already executed (for surface filtering).
cat > "$commit_path" <<'EOF'
{"ts":"2026-04-20T10:02:00Z","event":"commit.drafted","type":"feat","subject":"add oauth flow","confidence":0.8,"executed":false}
{"ts":"2026-04-20T10:07:00Z","event":"commit.drafted","type":"fix","subject":"null guard","executed":true,"sha":"abc123"}
EOF

# PR inbox — 1 pending record.
cat > "$pr_path" <<'EOF'
{"ts":"2026-04-20T10:12:00Z","event":"pr.drafted","title":"Add OAuth PKCE","branch":"feat/oauth","executed":false}
EOF

# ── 1. Discard middle record of branch inbox by ts ────────────────────
"$PY" "$INBOX" discard "$branch_path" "2026-04-20T10:05:00Z" 'reason="wrong workflow"'

line_count=$(wc -l < "$branch_path")
assert_eq "$line_count" "3" "branch inbox still has all 3 lines after discard"

# Exactly one line has discarded:true.
discarded_count=$(grep -c '"discarded":true' "$branch_path" || true)
assert_eq "$discarded_count" "1" "exactly one discarded line in branch inbox"

# Inspect the flipped record.
while IFS= read -r line; do
    ts="$(printf '%s' "$line" | jq -r '.ts')"
    if [[ "$ts" == "2026-04-20T10:05:00Z" ]]; then
        executed="$(printf '%s' "$line" | jq -r '.executed')"
        discarded="$(printf '%s' "$line" | jq -r '.discarded')"
        discarded_at="$(printf '%s' "$line" | jq -r '.discarded_at')"
        reason="$(printf '%s' "$line" | jq -r '.discard_reason')"
        assert_eq "$executed" "false" "executed stays false on discard"
        assert_eq "$discarded" "true" "discarded flipped to true"
        assert_ne "$discarded_at" "null" "discarded_at stamped"
        assert_eq "$reason" "wrong workflow" "reason stored without surrounding quotes"
    fi
done < "$branch_path"
ok "mark_discarded flips discarded:true + discarded_at + discard_reason"

# ── 2. read_pending excludes discarded records ────────────────────────
out="$("$PY" "$INBOX" read "$branch_path")"
count="$(printf '%s' "$out" | jq 'length')"
assert_eq "$count" "2" "read_pending returns 2 (not 3) after discard"
# The discarded ts must not appear.
contains_discarded="$(printf '%s' "$out" | jq '[.[] | select(.ts=="2026-04-20T10:05:00Z")] | length')"
assert_eq "$contains_discarded" "0" "discarded ts is filtered out of read_pending"
ok "read_pending excludes discarded records"

# ── 3. File stays valid JSONL ─────────────────────────────────────────
while IFS= read -r line; do
    printf '%s' "$line" | jq empty >/dev/null 2>&1 || fail "invalid JSON after discard: $line"
done < "$branch_path"
ok "every line in branch inbox remains valid JSON after discard"

# ── 4. Re-discarding same ts is a no-op (exit 0, one discarded line) ──
set +e
"$PY" "$INBOX" discard "$branch_path" "2026-04-20T10:05:00Z" 'reason="second try"' > /dev/null 2>&1
rc=$?
set -e
assert_exit_code "0" "$rc" "re-discard is idempotent (exit 0)"

# Still exactly one discarded line — idempotent didn't duplicate.
discarded_count=$(grep -c '"discarded":true' "$branch_path" || true)
assert_eq "$discarded_count" "1" "re-discard still yields one discarded line"

# Original reason preserved (no-op didn't overwrite).
while IFS= read -r line; do
    ts="$(printf '%s' "$line" | jq -r '.ts')"
    if [[ "$ts" == "2026-04-20T10:05:00Z" ]]; then
        reason="$(printf '%s' "$line" | jq -r '.discard_reason')"
        assert_eq "$reason" "wrong workflow" "re-discard preserved original reason"
    fi
done < "$branch_path"
ok "re-discarding the same ts is an idempotent no-op"

# ── 5. Unknown ts exits non-zero with message ─────────────────────────
set +e
err="$("$PY" "$INBOX" discard "$branch_path" "2099-01-01T00:00:00Z" 2>&1 >/dev/null)"
rc=$?
set -e
assert_exit_code "1" "$rc" "unknown ts exits 1"
assert_contains "$err" "no record with ts=" "unknown ts prints error"
ok "unknown ts exits 1 with a helpful stderr message"

# ── 6. discard_surface.py list aggregates + filters ───────────────────
list_out="$("$PY" "$SURFACE" list --root "$SBX_PY")"
tmp="$SANDBOX/list.json"
printf '%s' "$list_out" > "$tmp"
assert_json_valid "$tmp"

# After step 1, branch inbox has 2 pending (one was discarded),
# commit inbox has 1 pending (one already executed), pr inbox has 1.
# Total envelopes = 4.
total="$(jq 'length' "$tmp")"
assert_eq "$total" "4" "aggregator surfaces 4 pending envelopes across 3 inboxes"

# Each inbox label appears.
has_branch="$(jq '[.[] | select(.inbox=="branch")] | length' "$tmp")"
has_commit="$(jq '[.[] | select(.inbox=="commit")] | length' "$tmp")"
has_pr="$(jq '[.[] | select(.inbox=="pr")] | length' "$tmp")"
assert_eq "$has_branch" "2" "2 branch envelopes"
assert_eq "$has_commit" "1" "1 commit envelope"
assert_eq "$has_pr" "1" "1 pr envelope"

# Filter: --inbox commit returns only 1.
filt_out="$("$PY" "$SURFACE" list --root "$SBX_PY" --inbox commit)"
printf '%s' "$filt_out" > "$SANDBOX/filt.json"
filt_count="$(jq 'length' "$SANDBOX/filt.json")"
assert_eq "$filt_count" "1" "--inbox commit filters to 1 envelope"
filt_inbox="$(jq -r '.[0].inbox' "$SANDBOX/filt.json")"
assert_eq "$filt_inbox" "commit" "filtered envelope's inbox is 'commit'"
ok "discard_surface list aggregates all 3 inboxes and honors --inbox filter"

# ── 7. discard_surface.py resolve maps (inbox, index) → (path, ts) ────
resolve_out="$("$PY" "$SURFACE" resolve --root "$SBX_PY" --inbox branch --index 0)"
printf '%s' "$resolve_out" > "$SANDBOX/resolve.json"
assert_json_valid "$SANDBOX/resolve.json"
resolved_ts="$(jq -r '.ts' "$SANDBOX/resolve.json")"
# Index 0 = highest confidence → 0.9 record = ts 10:00:00Z.
assert_eq "$resolved_ts" "2026-04-20T10:00:00Z" "resolve returns highest-confidence ts at index 0"
resolved_path="$(jq -r '.path' "$SANDBOX/resolve.json")"
assert_contains "$resolved_path" "pending-actions.jsonl" "resolved path points to branch inbox"
ok "discard_surface resolve maps (inbox, index) → (path, ts) correctly"

# ── 8. Out-of-range index exits 1 ─────────────────────────────────────
set +e
"$PY" "$SURFACE" resolve --root "$SBX_PY" --inbox branch --index 99 > /dev/null 2>&1
rc=$?
set -e
assert_exit_code "1" "$rc" "out-of-range index exits 1"
ok "resolve with out-of-range index exits 1"
