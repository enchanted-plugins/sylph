#!/usr/bin/env bash
# LIVE integration test — opens a real draft PR against the sylph repo,
# round-trips it via the adapter, then closes it to avoid leaving cruft.
#
# Gated by $SYLPH_INTEGRATION=1. Not run by the default suite — this
# makes real network calls to api.github.com, needs push credentials
# (git credential-manager or $GH_TOKEN / $GITHUB_TOKEN), and leaves a
# brief closed PR in the repo's timeline.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

if [[ "${SYLPH_INTEGRATION:-0}" != "1" ]]; then
    echo "  skipped (set SYLPH_INTEGRATION=1 to run)"
    exit 0
fi

cd "$REPO_ROOT"
export PYTHONIOENCODING=utf-8

# Pre-flight: must be on the sylph repo, on main, clean tree.
remote="$(git remote get-url origin 2>&1)"
assert_contains "$remote" "enchanter-ai/sylph" "remote points at sylph repo"
current="$(git branch --show-current)"
assert_eq "$current" "main" "must start on main"
if [[ -n "$(git status --porcelain)" ]]; then
    fail "working tree dirty — commit or stash before running the live test"
fi

# Disposable feature branch + marker file so the PR has real content.
ts="$(date -u +%Y%m%d-%H%M%S)"
branch="sylph-integration-test-${ts}"
marker_file="tests/.integration-marker-${ts}.txt"

cleanup() {
    local rc=$?
    git checkout -q main 2>/dev/null || true
    git branch -D "$branch" 2>/dev/null || true
    git push -q origin --delete "$branch" 2>/dev/null || true
    rm -f "$REPO_ROOT/$marker_file" 2>/dev/null || true
    exit $rc
}
trap cleanup EXIT

git checkout -q -b "$branch"
printf 'Marker for live integration test %s\n' "$ts" > "$marker_file"
git add "$marker_file"
git -c user.email=sylph-test@local -c user.name="sylph-integration-test" \
    commit -q -m "test: live-integration marker ${ts}"
git push -q -u origin "$branch"
ok "feature branch pushed: $branch"

# Open the PR via the urllib adapter path.
pr_json="$("$PY" - <<PYEOF
import json, sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from adapters.github import GitHubAdapter

adapter = GitHubAdapter()
if not adapter.is_authenticated():
    print(json.dumps({"error": "adapter could not resolve a token"}))
    sys.exit(2)

repo = "enchanter-ai/sylph"
title = "test: sylph live integration ${ts}"
body = (
    "## What changed\n\n"
    "- Opened by tests/integration/test-live-github-pr.sh via Sylph's "
    "GitHubAdapter urllib path. Auto-closed by the same test.\n\n"
    "## Why\n\n"
    "Verifying W4 pr-lifecycle end-to-end against real GitHub.\n\n"
    "## How it was verified\n\n"
    "- is_authenticated() returned True via git-credential-manager.\n"
    "- open_pr POST /repos/enchanter-ai/sylph/pulls returned HTTP 201.\n"
    "- get_pr GET /repos/.../pulls/{number} round-tripped state + title.\n\n"
    "## Rollback plan\n\n"
    "PR is auto-closed; branch ${branch} is deleted locally + on the remote.\n"
)
pr = adapter.open_pr(repo, "main", "${branch}", title, body, draft=True)
print(json.dumps({
    "number": pr.number, "url": pr.url, "state": pr.state,
    "title": pr.title, "base": pr.base, "head": pr.head,
    "body_has_signature": "Sylph" in (pr.body or ""),
}))
PYEOF
)"

echo "  open_pr response: $pr_json"
if printf '%s' "$pr_json" | "$PY" -c 'import sys,json; d=json.load(sys.stdin); sys.exit(0 if not d.get("error") else 1)'; then
    pr_number="$(printf '%s' "$pr_json" | "$PY" -c 'import sys,json; print(json.load(sys.stdin)["number"])')"
    pr_state="$(printf '%s' "$pr_json" | "$PY" -c 'import sys,json; print(json.load(sys.stdin)["state"])')"
    pr_head="$(printf '%s' "$pr_json" | "$PY" -c 'import sys,json; print(json.load(sys.stdin)["head"])')"
    body_ok="$(printf '%s' "$pr_json" | "$PY" -c 'import sys,json; print(json.load(sys.stdin)["body_has_signature"])')"
else
    fail "live open_pr did not succeed: $pr_json"
fi

assert_eq "$pr_state" "draft" "PR opened in draft state"
assert_eq "$pr_head" "$branch" "PR head = feature branch"
assert_eq "$body_ok" "True" "PR body carries the Sylph signature"
ok "live open_pr: #${pr_number} opened as draft"

# Round-trip via get_pr.
round_json="$("$PY" - <<PYEOF
import json, sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from adapters.github import GitHubAdapter
adapter = GitHubAdapter()
pr = adapter.get_pr("enchanter-ai/sylph", ${pr_number})
print(json.dumps({"number": pr.number, "state": pr.state, "title": pr.title,
                  "base": pr.base, "head": pr.head}))
PYEOF
)"

round_state="$(printf '%s' "$round_json" | "$PY" -c 'import sys,json; print(json.load(sys.stdin)["state"])')"
round_title="$(printf '%s' "$round_json" | "$PY" -c 'import sys,json; print(json.load(sys.stdin)["title"])')"
assert_eq "$round_state" "draft" "get_pr round-trip: still draft"
assert_contains "$round_title" "live integration" "title survived the round-trip"
ok "get_pr round-trip: state + title preserved"

# Close the PR.
"$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from adapters.github import GitHubAdapter
adapter = GitHubAdapter()
adapter.close_pr("enchanter-ai/sylph", ${pr_number})
PYEOF
ok "close_pr: PR #${pr_number} closed"

# cleanup trap handles branch + remote deletion.
