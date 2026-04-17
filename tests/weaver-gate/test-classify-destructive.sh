#!/usr/bin/env bash
# Test: destructive_patterns.py classifies all 10 destructive ops correctly.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

# Pattern cases: cmd → expected (classification, exit_code)
cases=(
    "git push --force origin main|destructive|1"
    "git push -f origin main|destructive|1"
    "git push --force-with-lease origin main|destructive|1"
    "git rebase -i HEAD~3|destructive|1"
    "git rebase --interactive main|destructive|1"
    "git reset --hard HEAD~5|destructive|1"
    "git branch -D old-branch|destructive|1"
    "git push --delete origin feature|destructive|1"
    "git tag -d v1.0|destructive|1"
    "git filter-branch --tree-filter x|destructive|1"
    "git clean -fdx|protected-destructive|2"
    "git clean -fdX|protected-destructive|2"
)

for case_entry in "${cases[@]}"; do
    IFS='|' read -r cmd expected_class expected_exit <<< "$case_entry"
    set +e
    verdict="$("$PY" "$SHARED_SCRIPTS/destructive_patterns.py" "$cmd" 2>/dev/null)"
    actual_exit=$?
    set -e

    actual_class="$(printf '%s' "$verdict" | jq -r '.classification')"
    assert_eq "$actual_class" "$expected_class" "classify '$cmd'"
    assert_exit_code "$expected_exit" "$actual_exit" "exit for '$cmd'"
done

ok "12 destructive / protected-destructive patterns classified correctly"
