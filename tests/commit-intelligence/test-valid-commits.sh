#!/usr/bin/env bash
# Test: commit_classify.py passes every well-formed Conventional Commits
# message across all 11 canonical types plus breaking variants + footers.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

# Format: subject | body | valid(true/false) | type
cases=(
    "feat: add oauth pkce||true|feat"
    "feat(auth): add oauth pkce||true|feat"
    "fix: reject null session tokens||true|fix"
    "docs: clarify install steps||true|docs"
    "style: reflow imports||true|style"
    "refactor(db): extract connection pool||true|refactor"
    "perf: cache user lookups||true|perf"
    "test: cover edge case for empty input||true|test"
    "build: bump node version||true|build"
    "ci: add windows matrix||true|ci"
    "chore: update dependencies||true|chore"
    "revert: feat(auth): add oauth pkce||true|revert"
    "feat(api)!: remove v1 endpoint||true|feat"
)

for case_entry in "${cases[@]}"; do
    IFS='|' read -r subj body expected_valid expected_type <<< "$case_entry"
    if [[ -n "$body" ]]; then
        message="$subj

$body"
    else
        message="$subj"
    fi

    set +e
    result="$(printf '%s' "$message" | "$PY" "$SHARED_SCRIPTS/commit_classify.py" validate-stdin 2>/dev/null)"
    rc=$?
    set -e

    actual_valid="$(printf '%s' "$result" | jq -r '.valid')"
    actual_type="$(printf '%s' "$result" | jq -r '.type')"

    assert_eq "$actual_valid" "$expected_valid" "valid for '$subj'"
    assert_eq "$actual_type" "$expected_type" "type for '$subj'"
    assert_exit_code "0" "$rc" "exit code for '$subj'"
done

ok "13 canonical Conventional Commits forms accepted"

# Breaking change via footer only (no `!` in subject).
message="feat: add new config option

BREAKING CHANGE: removes old config format"
result="$(printf '%s' "$message" | "$PY" "$SHARED_SCRIPTS/commit_classify.py" validate-stdin)"
breaking="$(printf '%s' "$result" | jq -r '.breaking')"
assert_eq "$breaking" "true" "BREAKING CHANGE footer upgrades to breaking"
ok "BREAKING CHANGE footer detected and sets breaking=true"

# Co-author + sign-off footers parsed.
message="fix(session): handle expired tokens

Detected when refresh silently fails.

Co-authored-by: Alice <alice@example.com>
Signed-off-by: Bob <bob@example.com>"
result="$(printf '%s' "$message" | "$PY" "$SHARED_SCRIPTS/commit_classify.py" validate-stdin)"
footer_count="$(printf '%s' "$result" | jq '.footers | length')"
assert_eq "$footer_count" "2" "footer parser found 2 trailers"
ok "Co-authored-by + Signed-off-by footers parsed"
