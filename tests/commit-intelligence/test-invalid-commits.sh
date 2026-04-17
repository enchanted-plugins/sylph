#!/usr/bin/env bash
# Test: commit_classify.py rejects malformed messages and reports specific
# errors. Exit code is 1 for invalid, stdout carries error details.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

# Format: message | expected error substring
cases=(
    "fixed a bug|Subject does not match"
    "WIP: stuff|Subject does not match"
    "feature: new thing|Unknown type"
    ": empty type|Subject does not match"
)

for case_entry in "${cases[@]}"; do
    IFS='|' read -r message expected_err <<< "$case_entry"

    set +e
    result="$(printf '%s' "$message" | "$PY" "$SHARED_SCRIPTS/commit_classify.py" validate-stdin 2>/dev/null)"
    rc=$?
    set -e

    actual_valid="$(printf '%s' "$result" | jq -r '.valid')"
    actual_errs="$(printf '%s' "$result" | jq -r '.errors | @csv')"

    assert_eq "$actual_valid" "false" "valid=false for '$message'"
    assert_exit_code "1" "$rc" "exit 1 for '$message'"
    assert_contains "$actual_errs" "$expected_err" "error content for '$message'"
done

ok "4 malformed messages rejected with specific errors"

# Subject too long → error.
long_subject="feat: $(printf 'x%.0s' {1..80})"
result="$(printf '%s' "$long_subject" | "$PY" "$SHARED_SCRIPTS/commit_classify.py" validate-stdin 2>/dev/null || true)"
valid="$(printf '%s' "$result" | jq -r '.valid')"
assert_eq "$valid" "false" "over-long subject rejected"
errs="$(printf '%s' "$result" | jq -r '.errors | @csv')"
assert_contains "$errs" "Subject line" "error mentions Subject line"
ok "subject > 72 chars rejected"

# Missing blank line between subject and body → error.
message="feat: add x
body text directly after subject"
result="$(printf '%s' "$message" | "$PY" "$SHARED_SCRIPTS/commit_classify.py" validate-stdin 2>/dev/null || true)"
valid="$(printf '%s' "$result" | jq -r '.valid')"
errs="$(printf '%s' "$result" | jq -r '.errors | @csv')"
assert_eq "$valid" "false" "missing blank line rejected"
assert_contains "$errs" "blank line" "error mentions blank line"
ok "missing blank-line-after-subject rejected"

# Empty message → error.
result="$(printf '' | "$PY" "$SHARED_SCRIPTS/commit_classify.py" validate-stdin 2>/dev/null || true)"
valid="$(printf '%s' "$result" | jq -r '.valid')"
assert_eq "$valid" "false" "empty message rejected"
ok "empty message rejected"
