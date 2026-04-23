#!/usr/bin/env bash
# Integration test: the three canonical safe-amend scenarios flow through
# destructive_patterns.classify() and produce the right gate decision.
#
# Scenarios:
#   1. amend on unpushed HEAD       → safe     (exit 0)
#   2. amend on pushed HEAD         → destructive (exit 1)
#   3. amend --no-edit on pushed HEAD → destructive (exit 1)
#
# Also exercises `git commit -a --amend` argv shape and a non-amend git command
# in a pushed repo (must remain safe).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

new_sandbox > /dev/null

make_repo() {
    # Usage: make_repo <name> → path to a fresh single-commit repo.
    local name="$1"
    local dir="$SANDBOX/$name"
    mkdir -p "$dir"
    (
        cd "$dir"
        git init -q -b main
        git config user.email "test@sylph.local"
        git config user.name "sylph-test"
        git commit --allow-empty -q -m "seed"
    )
    printf '%s' "$dir"
}

simulate_push() {
    # Plant a remote-tracking ref at HEAD so is_head_pushed() sees the repo
    # as pushed without any network interaction.
    local dir="$1"
    (
        cd "$dir"
        git remote add origin "https://example.invalid/repo.git" 2>/dev/null || true
        git update-ref refs/remotes/origin/main HEAD
    )
}

classify_cli() {
    # Usage: classify_cli <repo_path> "<command>" → echoes "<exit>|<class>|<op>"
    local repo="$1" cmd="$2"
    local repo_py
    repo_py="$(py_path "$repo")"
    set +e
    local verdict
    verdict="$("$PY" "$SHARED_SCRIPTS/destructive_patterns.py" "$cmd" "$repo_py" 2>/dev/null)"
    local rc=$?
    set -e
    local cls op
    cls="$(printf '%s' "$verdict" | jq -r '.classification')"
    op="$(printf '%s' "$verdict" | jq -r '.op')"
    printf '%s|%s|%s' "$rc" "$cls" "$op"
}

# ── Scenario 1: amend on unpushed HEAD → safe ───────────────────────────

repo1="$(make_repo scenario1)"
result="$(classify_cli "$repo1" "git commit --amend")"
IFS='|' read -r rc cls op <<< "$result"
assert_exit_code "0" "$rc" "scenario 1: exit 0 (safe)"
assert_eq "$cls" "safe" "scenario 1: classification=safe"
ok "scenario 1: amend on unpushed HEAD → safe (allowed)"

# ── Scenario 2: amend on pushed HEAD → destructive (gated) ──────────────

repo2="$(make_repo scenario2)"
simulate_push "$repo2"
result="$(classify_cli "$repo2" "git commit --amend")"
IFS='|' read -r rc cls op <<< "$result"
assert_exit_code "1" "$rc" "scenario 2: exit 1 (destructive)"
assert_eq "$cls" "destructive" "scenario 2: classification=destructive"
assert_contains "$op" "--amend" "scenario 2: op names amend"
ok "scenario 2: amend on pushed HEAD → destructive (gated)"

# ── Scenario 3: amend --no-edit on pushed HEAD → destructive ────────────

repo3="$(make_repo scenario3)"
simulate_push "$repo3"
result="$(classify_cli "$repo3" "git commit --amend --no-edit")"
IFS='|' read -r rc cls op <<< "$result"
assert_exit_code "1" "$rc" "scenario 3: exit 1 (destructive)"
assert_eq "$cls" "destructive" "scenario 3: classification=destructive"
ok "scenario 3: amend --no-edit on pushed HEAD → still destructive"

# ── Extra coverage: `git commit -a --amend` on pushed HEAD ──────────────

repo4="$(make_repo scenario4)"
simulate_push "$repo4"
result="$(classify_cli "$repo4" "git commit -a --amend")"
IFS='|' read -r rc cls op <<< "$result"
assert_exit_code "1" "$rc" "scenario 4: -a --amend exits 1"
assert_eq "$cls" "destructive" "scenario 4: -a --amend destructive"
ok "scenario 4: git commit -a --amend on pushed HEAD → destructive"

# ── Regression: plain git status in pushed repo is still safe ───────────

result="$(classify_cli "$repo2" "git status")"
IFS='|' read -r rc cls op <<< "$result"
assert_exit_code "0" "$rc" "regression: status in pushed repo stays safe"
assert_eq "$cls" "safe" "regression: status classification=safe"
ok "regression: non-amend git command in pushed repo remains safe"

# ── Regression: plain git commit (no --amend) is still safe ─────────────

result="$(classify_cli "$repo2" "git commit -m update")"
IFS='|' read -r rc cls op <<< "$result"
assert_exit_code "0" "$rc" "regression: plain commit exits 0"
assert_eq "$cls" "safe" "regression: plain commit classification=safe"
ok "regression: plain git commit (no --amend) remains safe"
