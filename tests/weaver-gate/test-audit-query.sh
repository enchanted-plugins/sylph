#!/usr/bin/env bash
# Test: shared/scripts/audit_query.py — filtering, formatting, missing-file behavior.
#
# Seeds a synthetic audit.jsonl with 5 records covering every verdict flavor,
# then exercises each filter.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

QUERY="$SHARED_SCRIPTS/audit_query.py"
QUERY_PY="$(py_path "$QUERY")"
assert_file_exists "$QUERY" "audit_query.py present"

new_sandbox > /dev/null
audit="$SANDBOX/audit.jsonl"
audit_py="$(py_path "$audit")"

# Seed: 5 records.
#   1. safe op (verdict_exit=0)                            → allowed
#   2. force-push protected (exit 1, pattern specified)    → blocked
#   3. amend of pushed head                                → blocked
#   4. destructive_clean with bypass field                 → bypassed
#   5. filter_branch on 2026-04-18                         → blocked
cat > "$audit" <<'EOF'
{"ts":"2026-04-10T08:00:00Z","op":"status","cmd":"git status","verdict_exit":0,"recovery_days":0,"pattern":"safe"}
{"ts":"2026-04-15T09:22:17Z","op":"git push --force","cmd":"git push --force origin main","verdict_exit":1,"recovery_days":30,"pattern":"force_push_protected"}
{"ts":"2026-04-17T14:33:00Z","op":"git commit --amend","cmd":"git commit --amend --no-edit","verdict_exit":1,"recovery_days":7,"pattern":"amend_of_pushed_head"}
{"ts":"2026-04-19T11:08:42Z","op":"git clean -fdx","cmd":"git clean -fdx --yes-i-know","verdict_exit":2,"recovery_days":0,"pattern":"destructive_clean","bypass":"--yes-i-know"}
{"ts":"2026-04-18T16:44:10Z","op":"git filter-branch","cmd":"git filter-branch --tree-filter x","verdict_exit":1,"recovery_days":30,"pattern":"filter_branch"}
EOF

# ── Case 1: --pattern exact match ─────────────────────────────────────
out="$("$PY" "$QUERY_PY" --audit-log "$audit_py" --json --pattern amend_of_pushed_head)"
count="$(printf '%s' "$out" | jq 'length')"
assert_eq "$count" "1" "--pattern amend_of_pushed_head should return 1 record"
assert_eq "$(printf '%s' "$out" | jq -r '.[0].pattern')" "amend_of_pushed_head" "pattern field passes through"
assert_eq "$(printf '%s' "$out" | jq -r '.[0].decision')" "blocked" "amend_of_pushed_head decision=blocked"
ok "pattern filter: exact match returns 1 record"

# ── Case 2: --verdict bypassed ────────────────────────────────────────
out="$("$PY" "$QUERY_PY" --audit-log "$audit_py" --json --verdict bypassed)"
count="$(printf '%s' "$out" | jq 'length')"
assert_eq "$count" "1" "--verdict bypassed should return 1 record"
assert_eq "$(printf '%s' "$out" | jq -r '.[0].pattern')" "destructive_clean" "bypassed record is destructive_clean"
ok "verdict filter: bypassed returns 1 record"

# ── Case 3: --since mid-date subset ───────────────────────────────────
# --since 2026-04-17 → records on 04-17, 04-18, 04-19 (3 of 5).
out="$("$PY" "$QUERY_PY" --audit-log "$audit_py" --json --since 2026-04-17)"
count="$(printf '%s' "$out" | jq 'length')"
assert_eq "$count" "3" "--since 2026-04-17 should return 3 records (17, 18, 19)"
ok "since filter: inclusive lower bound"

# ── Case 4: --until upper bound (inclusive end-of-day) ───────────────
out="$("$PY" "$QUERY_PY" --audit-log "$audit_py" --json --until 2026-04-15)"
count="$(printf '%s' "$out" | jq 'length')"
assert_eq "$count" "2" "--until 2026-04-15 should return 2 records (10, 15)"
ok "until filter: end-of-day inclusive"

# ── Case 5: --verdict blocked (excludes allowed + bypassed) ──────────
out="$("$PY" "$QUERY_PY" --audit-log "$audit_py" --json --verdict blocked)"
count="$(printf '%s' "$out" | jq 'length')"
assert_eq "$count" "3" "--verdict blocked should return 3 records"
ok "verdict filter: blocked excludes allowed + bypassed"

# ── Case 6: --verdict allowed ────────────────────────────────────────
out="$("$PY" "$QUERY_PY" --audit-log "$audit_py" --json --verdict allowed)"
count="$(printf '%s' "$out" | jq 'length')"
assert_eq "$count" "1" "--verdict allowed should return 1 record"
assert_eq "$(printf '%s' "$out" | jq -r '.[0].op')" "status" "allowed record is 'status'"
ok "verdict filter: allowed isolates verdict_exit=0"

# ── Case 7: --tail N ─────────────────────────────────────────────────
out="$("$PY" "$QUERY_PY" --audit-log "$audit_py" --json --tail 2)"
count="$(printf '%s' "$out" | jq 'length')"
assert_eq "$count" "2" "--tail 2 keeps last 2 records"
ok "tail filter: keeps last N"

# ── Case 8: empty result is not an error (exit 0) ────────────────────
set +e
"$PY" "$QUERY_PY" --audit-log "$audit_py" --json --pattern does_not_exist > /dev/null 2>&1
rc=$?
set -e
assert_exit_code "0" "$rc" "empty result exits 0"
ok "empty result: exit 0, not an error"

# ── Case 9: missing audit.jsonl → 'no audit entries', exit 0 ─────────
missing_audit_py="$(py_path "$SANDBOX/does-not-exist.jsonl")"
set +e
output="$("$PY" "$QUERY_PY" --audit-log "$missing_audit_py" 2>&1)"
rc=$?
set -e
assert_exit_code "0" "$rc" "missing audit log exits 0"
assert_contains "$output" "no audit entries" "missing log prints no-entries message"
ok "missing audit.jsonl: exit 0 with message"

# ── Case 10: malformed line is skipped with stderr warning, not fatal ─
audit_bad="$SANDBOX/audit-bad.jsonl"
audit_bad_py="$(py_path "$audit_bad")"
cat > "$audit_bad" <<'EOF'
{"ts":"2026-04-15T09:22:17Z","op":"good","verdict_exit":0}
this is not json
{"ts":"2026-04-16T09:22:17Z","op":"also good","verdict_exit":0}
EOF
set +e
"$PY" "$QUERY_PY" --audit-log "$audit_bad_py" --json \
    >"$SANDBOX/good.out" 2>"$SANDBOX/err.out"
rc=$?
set -e
assert_exit_code "0" "$rc" "malformed line must not crash"
good_count="$(jq 'length' "$SANDBOX/good.out")"
assert_eq "$good_count" "2" "two valid records survive one garbage line"
err_out="$(cat "$SANDBOX/err.out")"
assert_contains "$err_out" "malformed" "malformed line produces stderr warning"
ok "malformed lines: skipped with warning, not fatal"

# ── Case 11: human-readable rendering sanity ─────────────────────────
human="$("$PY" "$QUERY_PY" --audit-log "$audit_py")"
assert_contains "$human" "Sylph audit" "human header present"
assert_contains "$human" "force_push_protected" "human output lists pattern"
assert_contains "$human" "BLOCKED" "human output uppercases verdict"
assert_contains "$human" "bypass: --yes-i-know" "bypass tag surfaced"
ok "human rendering: header + rows + bypass tag"
