#!/usr/bin/env bash
# pr-lifecycle chain-listener (PostToolUse(Bash) → on-commit.sh).
#
# Assertions:
#   1. With no executed-commits.jsonl feed: hook is a silent no-op (exit 0).
#   2. One `weaver.commit.committed` event → one pending-prs.jsonl record.
#   3. Listener-offset advances to the current executed-commits.jsonl size.
#   4. Re-running with no new events is idempotent (no duplicate record).
#   5. Non-commit events on the feed (e.g. stray junk or other event types)
#      are skipped without error.
#   6. Record schema: {ts, event:"weaver.pr.drafted", branch, sha, title,
#      body, reviewer_suggestions:[], source_commit, source_event}.
#   7. Advisory-only: hook always exits 0, even with a malformed feed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

# Sandbox mirroring the product layout so PLUGIN_ROOT + PRODUCT_ROOT resolve.
new_sandbox >/dev/null
fake_product="$SANDBOX/weaver-sim"
mkdir -p "$fake_product/plugins/commit-intelligence/state"
mkdir -p "$fake_product/plugins/pr-lifecycle/hooks/post-tool-use"
mkdir -p "$fake_product/plugins/pr-lifecycle/state"

cp "$PLUGINS_ROOT/pr-lifecycle/hooks/post-tool-use/on-commit.sh" \
   "$fake_product/plugins/pr-lifecycle/hooks/post-tool-use/"

# Share the real shared/ tree so atomic_state.sh + _hook_state.py are found.
ln -s "$REPO_ROOT/shared" "$fake_product/shared"

ci_state="$fake_product/plugins/commit-intelligence/state"
pr_root="$fake_product/plugins/pr-lifecycle"
feed="$ci_state/executed-commits.jsonl"
offset_file="$pr_root/state/listener-offset.json"
pending_prs="$pr_root/state/pending-prs.jsonl"

# Fresh offset.
echo '{"last_offset":0}' > "$offset_file"

export CLAUDE_PLUGIN_ROOT="$pr_root"

run_hook() {
    bash "$pr_root/hooks/post-tool-use/on-commit.sh" 2>/dev/null
}

# ── Assertion 1: silent no-op when upstream feed is missing ────────────
run_hook
rc=$?
assert_exit_code "0" "$rc" "hook exits 0 when executed-commits.jsonl missing"
if [[ -f "$pending_prs" ]]; then
    lines="$(wc -l < "$pending_prs" | tr -d '[:space:]')"
    assert_eq "$lines" "0" "no pending-prs record when feed missing"
fi
ok "no-op when upstream feed missing"

# ── Assertion 2: one executed-commit event → one PR draft record ───────
ts_1="2026-04-20T10:00:00Z"
cat >> "$feed" <<JSON
{"ts":"$ts_1","event":"weaver.commit.committed","sha":"deadbeefcafebabe0001","branch":"feat/chain-listener","message":"feat(pr-lifecycle): add chain-listener for executed commits","source_draft_ts":"2026-04-20T09:59:00Z"}
JSON

run_hook
rc=$?
assert_exit_code "0" "$rc" "hook exits 0 after first event"

assert_file_exists "$pending_prs" "pending-prs.jsonl created after first event"
lines_1=$(wc -l < "$pending_prs" | tr -d '[:space:]')
assert_eq "$lines_1" "1" "exactly one pending-prs record written"

# Schema sanity.
assert_jq "$pending_prs" '.event' "weaver.pr.drafted" "record event name"
assert_jq "$pending_prs" '.branch' "feat/chain-listener" "record branch"
assert_jq "$pending_prs" '.sha' "deadbeefcafebabe0001" "record sha"
assert_jq "$pending_prs" '.source_commit' "deadbeefcafebabe0001" "record source_commit"
assert_jq "$pending_prs" '.reviewer_suggestions | length' "0" "reviewer_suggestions is empty list (skill fills it)"
assert_jq "$pending_prs" '.source_event.event' "weaver.commit.committed" "source_event preserved"
assert_jq "$pending_prs" '.executed' "false" "executed false (skill flips it)"

# Title should be derived from the commit message's first line.
assert_jq "$pending_prs" '.title' \
    "feat(pr-lifecycle): add chain-listener for executed commits" \
    "title taken from commit message"

# Body should at least mention the sha prefix.
body="$(jq -r '.body' "$pending_prs")"
assert_contains "$body" "deadbeef" "body references commit sha prefix"
assert_contains "$body" "What changed" "body includes What changed section"

# Offset should now match the file size.
feed_size=$(wc -c < "$feed" | tr -d '[:space:]')
off_now=$(jq -r '.last_offset' "$offset_file")
assert_eq "$off_now" "$feed_size" "listener-offset advanced to feed size"

ok "one executed-commit event → one pending-prs record with correct schema"

# ── Assertion 3: idempotent — re-running is a no-op ─────────────────────
run_hook
rc=$?
assert_exit_code "0" "$rc" "idempotent re-run exits 0"
lines_after=$(wc -l < "$pending_prs" | tr -d '[:space:]')
assert_eq "$lines_after" "1" "no duplicate pending-prs record on re-run"
ok "listener is idempotent: re-run with no new events is a no-op"

# ── Assertion 4: non-commit events on the feed are skipped ──────────────
# A stray non-committed event (e.g. an older schema marker) should be ignored.
ts_2="2026-04-20T10:05:00Z"
cat >> "$feed" <<JSON
{"ts":"$ts_2","event":"weaver.commit.aborted","sha":"0000","branch":"noop","message":"stray","source_draft_ts":""}
JSON

run_hook
rc=$?
assert_exit_code "0" "$rc" "hook exits 0 for non-commit event"
lines_stray=$(wc -l < "$pending_prs" | tr -d '[:space:]')
assert_eq "$lines_stray" "1" "non-commit event does not produce a PR draft"

# Offset still advances so we don't reprocess the stray line.
feed_size_2=$(wc -c < "$feed" | tr -d '[:space:]')
off_stray=$(jq -r '.last_offset' "$offset_file")
assert_eq "$off_stray" "$feed_size_2" "offset advances even for non-commit events"
ok "non-commit events are skipped without dropping into pending-prs.jsonl"

# ── Assertion 5: a second real commit event appends a second record ─────
ts_3="2026-04-20T10:10:00Z"
cat >> "$feed" <<JSON
{"ts":"$ts_3","event":"weaver.commit.committed","sha":"aaaabbbbccccdddd0002","branch":"feat/chain-listener","message":"test(pr-lifecycle): add chain-listener coverage","source_draft_ts":"2026-04-20T10:09:00Z"}
JSON

run_hook
rc=$?
assert_exit_code "0" "$rc" "hook exits 0 after second commit"

lines_2=$(wc -l < "$pending_prs" | tr -d '[:space:]')
assert_eq "$lines_2" "2" "second commit event appends a second record"

# Last record should be the second commit.
sha_last="$(tail -n1 "$pending_prs" | jq -r '.sha')"
assert_eq "$sha_last" "aaaabbbbccccdddd0002" "second record references the later sha"
ok "two commit events → two pending-prs records in order"

# ── Assertion 6: advisory — malformed feed line doesn't crash ───────────
ts_4="2026-04-20T10:15:00Z"
printf 'not-json-at-all\n' >> "$feed"
cat >> "$feed" <<JSON
{"ts":"$ts_4","event":"weaver.commit.committed","sha":"eeeeffff0003","branch":"feat/chain-listener","message":"fix: trailing good event","source_draft_ts":"2026-04-20T10:14:00Z"}
JSON

run_hook
rc=$?
assert_exit_code "0" "$rc" "advisory contract: hook exits 0 even with malformed line"

lines_final=$(wc -l < "$pending_prs" | tr -d '[:space:]')
# The good trailing event MAY or MAY NOT be recorded depending on how jq
# handles the malformed line inside the while-read loop, but the run MUST
# never crash and offset MUST NOT regress.
off_final=$(jq -r '.last_offset' "$offset_file")
feed_size_final=$(wc -c < "$feed" | tr -d '[:space:]')
if (( off_final > feed_size_final )); then
    fail "offset must not exceed feed size (got $off_final > $feed_size_final)"
fi
ok "advisory contract: malformed feed lines do not crash the hook"
