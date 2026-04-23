#!/usr/bin/env bash
# Test: /sylph:branch's inbox consumer contract.
#
# Exercises shared/scripts/pending_inbox.py — the consumer side of the
# branch-workflow hook pipeline. Coverage:
#
#   1. read on missing file            → []
#   2. read on empty file              → []
#   3. read returns only executed=false records
#   4. read sorts by descending confidence (highest default shown first)
#   5. read tolerates corrupt JSONL lines
#   6. mark flips the matching ts to executed=true + executed_at + extras
#   7. mark preserves ordering of surrounding records
#   8. mark returns non-zero when no record matches
#   9. read + mark roundtrip: the record is filtered out on the next read
#  10. file stays valid JSONL after mark (jq empty on every line)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

INBOX="$SHARED_SCRIPTS/pending_inbox.py"
assert_file_exists "$INBOX" "pending_inbox.py missing"

new_sandbox > /dev/null
tmp="$SANDBOX"

pending_path="$tmp/pending-actions.jsonl"

# ── 1. read on missing file ──────────────────────────────────────────
out="$("$PY" "$INBOX" read "$tmp/does-not-exist.jsonl")"
assert_eq "$out" "[]" "read on missing file → []"
ok "read on missing file returns empty array"

# ── 2. read on empty file ────────────────────────────────────────────
: > "$pending_path"
out="$("$PY" "$INBOX" read "$pending_path")"
assert_eq "$out" "[]" "read on empty file → []"
ok "read on empty file returns empty array"

# ── 3. read filters to executed=false ────────────────────────────────
# Three records: two pending (one high-confidence, one low), one already done.
cat > "$pending_path" <<'EOF'
{"ts":"2026-04-20T10:00:00Z","event":"branch.suggested","workflow":"github-flow","dominant_file":"src/auth.py","confidence":0.85,"source_event":{"ts":"2026-04-20T09:59:58Z","event":"sylph.task.boundary.detected","closed_cluster":{"id":"c1"}},"executed":false}
{"ts":"2026-04-20T10:05:00Z","event":"branch.suggested","workflow":"unknown","dominant_file":"README.md","confidence":0.3,"source_event":{"ts":"2026-04-20T10:04:59Z","event":"sylph.task.boundary.detected","closed_cluster":{"id":"c2"}},"executed":false}
{"ts":"2026-04-20T09:00:00Z","event":"branch.suggested","workflow":"trunk-based","dominant_file":"src/old.py","confidence":0.9,"source_event":{"ts":"2026-04-20T08:59:59Z","event":"sylph.task.boundary.detected","closed_cluster":{"id":"c0"}},"executed":true,"executed_at":"2026-04-20T09:01:00Z","branch_name":"dave/old-fix"}
EOF

out="$("$PY" "$INBOX" read "$pending_path")"
count="$(printf '%s' "$out" | jq 'length')"
assert_eq "$count" "2" "read returns 2 pending records"

# Top record (element 0) must be the high-confidence one.
top_ts="$(printf '%s' "$out" | jq -r '.[0].ts')"
assert_eq "$top_ts" "2026-04-20T10:00:00Z" "top pending record is the 0.85-confidence one"
top_conf="$(printf '%s' "$out" | jq -r '.[0].confidence')"
assert_eq "$top_conf" "0.85" "top confidence is 0.85"
ok "read filters to executed=false and sorts by descending confidence"

# ── 4. confidence ordering: higher wins ──────────────────────────────
second_conf="$(printf '%s' "$out" | jq -r '.[1].confidence')"
assert_eq "$second_conf" "0.3" "second record is the 0.3-confidence fallback"
ok "read orders pending records by confidence desc"

# ── 5. tolerates corrupt JSONL line ──────────────────────────────────
corrupt_path="$tmp/corrupt.jsonl"
cat > "$corrupt_path" <<'EOF'
{"ts":"2026-04-20T11:00:00Z","event":"branch.suggested","confidence":0.7,"executed":false}
{"ts":"2026-04-20T11:01:00Z", "event": "branch.suggested"
{"ts":"2026-04-20T11:02:00Z","event":"branch.suggested","confidence":0.6,"executed":false}
EOF
out="$("$PY" "$INBOX" read "$corrupt_path")"
count="$(printf '%s' "$out" | jq 'length')"
assert_eq "$count" "2" "corrupt line skipped; 2 valid records surfaced"
ok "read skips corrupt JSONL lines silently"

# ── 6. mark flips the matching ts to executed=true + extras ──────────
"$PY" "$INBOX" mark "$pending_path" "2026-04-20T10:00:00Z" branch_name=feat/add-oauth-pkce

# JSONL is line-per-record; jq doesn't treat the whole file as one doc, so
# we verify per-line instead of with assert_jq.
line_count=$(wc -l < "$pending_path")
assert_eq "$line_count" "3" "file still has 3 lines after mark"

# Find the flipped record and assert its shape.
while IFS= read -r line; do
    ts="$(printf '%s' "$line" | jq -r '.ts')"
    if [[ "$ts" == "2026-04-20T10:00:00Z" ]]; then
        executed="$(printf '%s' "$line" | jq -r '.executed')"
        branch="$(printf '%s' "$line" | jq -r '.branch_name')"
        executed_at="$(printf '%s' "$line" | jq -r '.executed_at')"
        assert_eq "$executed" "true" "executed flipped to true"
        assert_eq "$branch" "feat/add-oauth-pkce" "branch_name extra merged in"
        assert_ne "$executed_at" "null" "executed_at stamped"
    fi
done < "$pending_path"
ok "mark flips executed=true and merges extras (branch_name, executed_at)"

# ── 7. ordering preserved ────────────────────────────────────────────
first_ts="$(sed -n '1p' "$pending_path" | jq -r '.ts')"
second_ts="$(sed -n '2p' "$pending_path" | jq -r '.ts')"
third_ts="$(sed -n '3p' "$pending_path" | jq -r '.ts')"
assert_eq "$first_ts" "2026-04-20T10:00:00Z" "line 1 ts preserved"
assert_eq "$second_ts" "2026-04-20T10:05:00Z" "line 2 ts preserved"
assert_eq "$third_ts" "2026-04-20T09:00:00Z" "line 3 ts preserved"
ok "mark preserves original line ordering"

# ── 8. mark with no match returns non-zero ───────────────────────────
set +e
"$PY" "$INBOX" mark "$pending_path" "2030-01-01T00:00:00Z" > /dev/null 2>&1
rc=$?
set -e
assert_exit_code "1" "$rc" "mark with no match exits 1"
ok "mark returns exit 1 when no record matches"

# ── 9. roundtrip: post-mark read excludes the flipped record ─────────
out="$("$PY" "$INBOX" read "$pending_path")"
count="$(printf '%s' "$out" | jq 'length')"
assert_eq "$count" "1" "post-mark read returns only the remaining pending record"
remaining_ts="$(printf '%s' "$out" | jq -r '.[0].ts')"
assert_eq "$remaining_ts" "2026-04-20T10:05:00Z" "remaining pending is the 0.3-confidence one"
ok "roundtrip: flipped record is filtered out of next read"

# ── 10. file stays valid JSONL after mark ────────────────────────────
while IFS= read -r line; do
    printf '%s' "$line" | jq empty >/dev/null 2>&1 || fail "invalid JSON after mark: $line"
done < "$pending_path"
ok "every line in pending-actions.jsonl is valid JSON after mark"
