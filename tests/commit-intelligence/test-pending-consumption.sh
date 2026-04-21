#!/usr/bin/env bash
# Test: /weaver:commit's inbox consumer contract.
#
# Exercises shared/scripts/pending_inbox.py against pending-drafts.jsonl —
# the commit-intelligence side of the hook pipeline. Coverage mirrors the
# branch-workflow test suite but against the commit draft schema:
#   {ts, event:"commit.drafted", suggested_type, dominant_file, files,
#    event_count, source_event, executed:false}
#
# Cases:
#   1. read on missing file                     → []
#   2. read on empty file                       → []
#   3. read filters to executed=false and preserves commit-draft fields
#   4. read order is FIFO when confidence is absent (stable sort by ts asc)
#   5. mark flips executed=true and merges sha=<sha> extra
#   6. mark preserves ordering across pending + executed records
#   7. post-mark read excludes the flipped record
#   8. mark with no match returns exit 1
#   9. extra fields survive the rewrite as plain strings
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

INBOX="$SHARED_SCRIPTS/pending_inbox.py"
assert_file_exists "$INBOX" "pending_inbox.py missing"

new_sandbox > /dev/null
tmp="$SANDBOX"

drafts_path="$tmp/pending-drafts.jsonl"

# ── 1. read on missing file ──────────────────────────────────────────
out="$("$PY" "$INBOX" read "$tmp/nope.jsonl")"
assert_eq "$out" "[]" "read on missing file → []"
ok "read on missing file returns empty array"

# ── 2. read on empty file ────────────────────────────────────────────
: > "$drafts_path"
out="$("$PY" "$INBOX" read "$drafts_path")"
assert_eq "$out" "[]" "read on empty file → []"
ok "read on empty file returns empty array"

# ── 3. read filters to executed=false ────────────────────────────────
# Three records: two pending, one already done.
cat > "$drafts_path" <<'EOF'
{"ts":"2026-04-20T10:00:00Z","event":"commit.drafted","suggested_type":"feat","dominant_file":"src/auth.py","files":["src/auth.py","src/session.py"],"event_count":4,"source_event":{"ts":"2026-04-20T09:59:58Z","event":"weaver.task.boundary.detected","closed_cluster":{"id":"c1"}},"executed":false}
{"ts":"2026-04-20T10:05:00Z","event":"commit.drafted","suggested_type":"docs","dominant_file":"README.md","files":["README.md"],"event_count":1,"source_event":{"ts":"2026-04-20T10:04:59Z","event":"weaver.task.boundary.detected","closed_cluster":{"id":"c2"}},"executed":false}
{"ts":"2026-04-20T09:00:00Z","event":"commit.drafted","suggested_type":"fix","dominant_file":"src/old.py","files":["src/old.py"],"event_count":2,"source_event":{"ts":"2026-04-20T08:59:59Z","event":"weaver.task.boundary.detected","closed_cluster":{"id":"c0"}},"executed":true,"executed_at":"2026-04-20T09:01:00Z","sha":"abc1234"}
EOF

out="$("$PY" "$INBOX" read "$drafts_path")"
count="$(printf '%s' "$out" | jq 'length')"
assert_eq "$count" "2" "read returns 2 pending commit drafts"

# Check the commit-draft-specific fields are round-tripped.
top_type="$(printf '%s' "$out" | jq -r '.[0].suggested_type')"
top_files_len="$(printf '%s' "$out" | jq '.[0].files | length')"
top_count="$(printf '%s' "$out" | jq -r '.[0].event_count')"
assert_eq "$top_type" "feat" "top suggested_type preserved"
assert_eq "$top_files_len" "2" "top files array preserved (2 elements)"
assert_eq "$top_count" "4" "top event_count preserved"
ok "read preserves commit-draft schema fields (suggested_type, files, event_count)"

# ── 4. FIFO order when confidence is absent ──────────────────────────
# Records have no confidence key — Python falls back to 0.0 for all, so the
# sort is stable and preserves insertion order (older ts first).
first_ts="$(printf '%s' "$out" | jq -r '.[0].ts')"
second_ts="$(printf '%s' "$out" | jq -r '.[1].ts')"
assert_eq "$first_ts" "2026-04-20T10:00:00Z" "FIFO: earlier ts first"
assert_eq "$second_ts" "2026-04-20T10:05:00Z" "FIFO: later ts second"
ok "read preserves FIFO order when confidence is absent"

# ── 5. mark flips + merges sha ───────────────────────────────────────
"$PY" "$INBOX" mark "$drafts_path" "2026-04-20T10:00:00Z" sha=deadbeef

line_count=$(wc -l < "$drafts_path")
assert_eq "$line_count" "3" "file still has 3 lines after mark"

while IFS= read -r line; do
    ts="$(printf '%s' "$line" | jq -r '.ts')"
    if [[ "$ts" == "2026-04-20T10:00:00Z" ]]; then
        executed="$(printf '%s' "$line" | jq -r '.executed')"
        sha="$(printf '%s' "$line" | jq -r '.sha')"
        executed_at="$(printf '%s' "$line" | jq -r '.executed_at')"
        assert_eq "$executed" "true" "executed flipped to true"
        assert_eq "$sha" "deadbeef" "sha extra merged in"
        assert_ne "$executed_at" "null" "executed_at stamped"
    fi
done < "$drafts_path"
ok "mark flips executed=true and merges sha=<sha>"

# ── 6. ordering preserved after mark ─────────────────────────────────
f1_ts="$(sed -n '1p' "$drafts_path" | jq -r '.ts')"
f2_ts="$(sed -n '2p' "$drafts_path" | jq -r '.ts')"
f3_ts="$(sed -n '3p' "$drafts_path" | jq -r '.ts')"
assert_eq "$f1_ts" "2026-04-20T10:00:00Z" "line 1 ts preserved"
assert_eq "$f2_ts" "2026-04-20T10:05:00Z" "line 2 ts preserved"
assert_eq "$f3_ts" "2026-04-20T09:00:00Z" "line 3 ts preserved"
ok "mark preserves original line ordering across pending+executed"

# ── 7. post-mark read excludes flipped record ────────────────────────
out="$("$PY" "$INBOX" read "$drafts_path")"
count="$(printf '%s' "$out" | jq 'length')"
assert_eq "$count" "1" "post-mark read returns only the remaining draft"
remaining_type="$(printf '%s' "$out" | jq -r '.[0].suggested_type')"
assert_eq "$remaining_type" "docs" "remaining draft is the docs one"
ok "roundtrip: flipped commit-draft is filtered out of next read"

# ── 8. mark with no match returns non-zero ───────────────────────────
set +e
"$PY" "$INBOX" mark "$drafts_path" "2030-01-01T00:00:00Z" sha=zzz > /dev/null 2>&1
rc=$?
set -e
assert_exit_code "1" "$rc" "mark with no match exits 1"
ok "mark returns exit 1 when no commit-draft matches"

# ── 9. extra fields survive as plain strings ─────────────────────────
# Re-read the flipped record and confirm sha is a string, not parsed as a
# number (deadbeef looks hex-ish but pending_inbox passes extras as strings).
while IFS= read -r line; do
    ts="$(printf '%s' "$line" | jq -r '.ts')"
    if [[ "$ts" == "2026-04-20T10:00:00Z" ]]; then
        sha_type="$(printf '%s' "$line" | jq -r '.sha | type')"
        assert_eq "$sha_type" "string" "sha extra serialized as string"
    fi
done < "$drafts_path"
ok "extras merged via CLI are serialized as JSON strings"
