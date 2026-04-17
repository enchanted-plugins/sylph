#!/usr/bin/env bash
# Test: destructive_patterns.py treats safe git and non-git commands as safe.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

safe_cmds=(
    "git status"
    "git log --oneline"
    "git diff HEAD"
    "git commit -m fix"
    "git push origin main"
    "git branch -d merged-branch"
    "git rebase main"
    "git reset HEAD"
    "git clean -n"
    "ls -la"
    "echo hello"
    "python script.py"
)

for cmd in "${safe_cmds[@]}"; do
    set +e
    verdict="$("$PY" "$SHARED_SCRIPTS/destructive_patterns.py" "$cmd" 2>/dev/null)"
    actual_exit=$?
    set -e

    actual_class="$(printf '%s' "$verdict" | jq -r '.classification')"
    assert_eq "$actual_class" "safe" "classify '$cmd'"
    assert_exit_code "0" "$actual_exit" "exit for '$cmd'"
done

ok "12 safe + non-git commands classified correctly"
