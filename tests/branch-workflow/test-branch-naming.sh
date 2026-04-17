#!/usr/bin/env bash
# Test: workflow_detect.py suggest-branch produces names per workflow convention.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

suggest() {
    local workflow="$1" type="$2" slug="$3"
    "$PY" "$SHARED_SCRIPTS/workflow_detect.py" suggest-branch "$workflow" "$type" "$slug" | jq -r '.branch'
}

# GitHub Flow: type/slug
result="$(suggest github-flow feat 'add oauth pkce support')"
assert_eq "$result" "feat/add-oauth-pkce-support" "github-flow feat branch"
result="$(suggest github-flow fix 'null session')"
assert_eq "$result" "fix/null-session" "github-flow fix branch"
ok "github-flow: type/slug naming"

# GitFlow: feature|bugfix|hotfix/slug
assert_eq "$(suggest gitflow feat 'export v2')" "feature/export-v2" "gitflow feat → feature/"
assert_eq "$(suggest gitflow fix 'crash on signup')" "bugfix/crash-on-signup" "gitflow fix → bugfix/"
assert_eq "$(suggest gitflow hotfix 'prod outage')" "hotfix/prod-outage" "gitflow hotfix → hotfix/"
ok "gitflow: feature|bugfix|hotfix prefix mapping"

# Release Flow: feature/slug normal, hotfix/slug for fixes
assert_eq "$(suggest release-flow feat 'checkout v2')" "feature/checkout-v2" "release-flow feat → feature/"
assert_eq "$(suggest release-flow fix 'regression')" "hotfix/regression" "release-flow fix → hotfix/"
ok "release-flow: feature/hotfix routing"

# Stacked diffs: bare slug
assert_eq "$(suggest stacked-diffs feat 'cache refactor')" "cache-refactor" "stacked-diffs: bare slug"
assert_eq "$(suggest stacked-diffs - 'pr2')" "pr2" "stacked-diffs: no type prefix"
ok "stacked-diffs: bare topic names"

# Unknown: wip/slug fallback
assert_eq "$(suggest unknown feat 'explore')" "wip/explore" "unknown → wip/"
ok "unknown: wip/ fallback"
