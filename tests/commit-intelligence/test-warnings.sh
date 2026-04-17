#!/usr/bin/env bash
# Test: commit_classify.py surfaces warnings for soft violations (period at
# end of subject, uppercase first word) without rejecting the commit.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

# Trailing period → warning.
result="$(printf 'feat: add thing.' | "$PY" "$SHARED_SCRIPTS/commit_classify.py" validate-stdin 2>/dev/null)"
valid="$(printf '%s' "$result" | jq -r '.valid')"
warnings="$(printf '%s' "$result" | jq -r '.warnings | @csv')"
assert_eq "$valid" "true" "trailing period: still valid"
assert_contains "$warnings" "period" "warning about trailing period"
ok "trailing period warns, does not reject"

# Uppercase first word → warning.
result="$(printf 'feat: Add thing' | "$PY" "$SHARED_SCRIPTS/commit_classify.py" validate-stdin 2>/dev/null)"
valid="$(printf '%s' "$result" | jq -r '.valid')"
warnings="$(printf '%s' "$result" | jq -r '.warnings | @csv')"
assert_eq "$valid" "true" "uppercase: still valid"
assert_contains "$warnings" "uppercase" "warning about uppercase start"
ok "uppercase first word warns, does not reject"

# BREAKING CHANGE footer without `!` in subject → warning.
message="feat(api): refactor auth

BREAKING CHANGE: drops v1 endpoints"
result="$(printf '%s' "$message" | "$PY" "$SHARED_SCRIPTS/commit_classify.py" validate-stdin 2>/dev/null)"
warnings="$(printf '%s' "$result" | jq -r '.warnings | @csv')"
assert_contains "$warnings" "BREAKING CHANGE" "warning suggests '!' in subject"
ok "BREAKING CHANGE without '!' warns"
