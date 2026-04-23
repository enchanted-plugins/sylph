#!/usr/bin/env bash
# Unit tests for shared/scripts/amend_safety.py.
#
# Exercises is_head_pushed() and classify_amend() directly on temp-git-repo
# fixtures. Pure Python call via python3 -c — no hook layer involved.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

# Sandbox root — every scenario gets its own repo under it.
new_sandbox > /dev/null

make_repo() {
    # Usage: make_repo <name> → echoes path to a fresh, single-commit repo.
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

# Helper: run a short Python snippet with amend_safety importable.
amend_py() {
    # Usage: amend_py <repo_path> <python_snippet>
    local repo="$1" snippet="$2"
    local repo_py snippet_full
    repo_py="$(py_path "$repo")"
    snippet_full="import sys; sys.path.insert(0, r'$SHARED_SCRIPTS_PY'); from amend_safety import is_head_pushed, classify_amend, is_amend_invocation; $snippet"
    "$PY" -c "$snippet_full"
}

# ── is_amend_invocation ────────────────────────────────────────────────

result="$(amend_py "$SANDBOX" "print(is_amend_invocation(['git','commit','--amend']))")"
assert_eq "$result" "True" "is_amend_invocation: basic --amend"

result="$(amend_py "$SANDBOX" "print(is_amend_invocation(['git','commit','--amend','--no-edit']))")"
assert_eq "$result" "True" "is_amend_invocation: --amend --no-edit"

result="$(amend_py "$SANDBOX" "print(is_amend_invocation(['git','commit','-a','--amend']))")"
assert_eq "$result" "True" "is_amend_invocation: -a --amend"

result="$(amend_py "$SANDBOX" "print(is_amend_invocation(['git','commit','-m','fix']))")"
assert_eq "$result" "False" "is_amend_invocation: plain commit is not amend"

result="$(amend_py "$SANDBOX" "print(is_amend_invocation(['git','push','--amend']))")"
assert_eq "$result" "False" "is_amend_invocation: --amend on non-commit subcommand ignored"

ok "is_amend_invocation: 5 argv-shape cases"

# ── is_head_pushed: no-remote repo → not pushed ────────────────────────

repo_noremote="$(make_repo noremote)"
result="$(amend_py "$repo_noremote" "
pushed, sha, refs = is_head_pushed(r'$(py_path "$repo_noremote")')
print('pushed=' + str(pushed))
print('refs_len=' + str(len(refs)))
print('sha_len=' + str(len(sha or '')))
")"
assert_contains "$result" "pushed=False" "no remote → not pushed"
assert_contains "$result" "refs_len=0" "no remote → zero containing refs"
assert_contains "$result" "sha_len=40" "sha is a 40-char hex"
ok "is_head_pushed: local-only repo classified as not-pushed"

# ── is_head_pushed: simulated pushed → pushed ──────────────────────────

repo_pushed="$(make_repo pushed)"
(
    cd "$repo_pushed"
    git remote add origin "https://example.invalid/repo.git"
    # Simulate a push by planting a remote-tracking ref at current HEAD.
    git update-ref refs/remotes/origin/main HEAD
)
result="$(amend_py "$repo_pushed" "
pushed, sha, refs = is_head_pushed(r'$(py_path "$repo_pushed")')
print('pushed=' + str(pushed))
print('refs=' + ','.join(refs))
")"
assert_contains "$result" "pushed=True" "simulated remote-tracking ref → pushed"
assert_contains "$result" "refs/remotes/origin/main" "containing ref reported"
ok "is_head_pushed: simulated pushed HEAD classified as pushed"

# ── is_head_pushed: new local commit after pushed ref → not pushed ─────

repo_ahead="$(make_repo ahead)"
(
    cd "$repo_ahead"
    git remote add origin "https://example.invalid/repo.git"
    git update-ref refs/remotes/origin/main HEAD
    # New commit on top of pushed ref → HEAD no longer on any remote ref.
    git commit --allow-empty -q -m "local work"
)
result="$(amend_py "$repo_ahead" "
pushed, sha, refs = is_head_pushed(r'$(py_path "$repo_ahead")')
print('pushed=' + str(pushed))
")"
assert_contains "$result" "pushed=False" "local commits ahead of remote → not pushed"
ok "is_head_pushed: ahead-of-remote HEAD classified as not-pushed"

# ── classify_amend: non-amend argv → is_amend=False ────────────────────

result="$(amend_py "$repo_pushed" "
v = classify_amend(['git','status'], r'$(py_path "$repo_pushed")')
print('amend=' + str(v.is_amend))
print('destructive=' + str(v.is_destructive))
")"
assert_contains "$result" "amend=False" "non-amend → is_amend False"
assert_contains "$result" "destructive=False" "non-amend → is_destructive False"
ok "classify_amend: non-amend bypassed"

# ── classify_amend: amend + pushed → destructive ───────────────────────

result="$(amend_py "$repo_pushed" "
v = classify_amend(['git','commit','--amend'], r'$(py_path "$repo_pushed")')
print('amend=' + str(v.is_amend))
print('destructive=' + str(v.is_destructive))
")"
assert_contains "$result" "amend=True" "pushed + amend → is_amend True"
assert_contains "$result" "destructive=True" "pushed + amend → is_destructive True"
ok "classify_amend: pushed HEAD amend flagged destructive"

# ── classify_amend: amend + unpushed → safe ────────────────────────────

result="$(amend_py "$repo_noremote" "
v = classify_amend(['git','commit','--amend','--no-edit'], r'$(py_path "$repo_noremote")')
print('amend=' + str(v.is_amend))
print('destructive=' + str(v.is_destructive))
")"
assert_contains "$result" "amend=True" "unpushed + amend → is_amend True"
assert_contains "$result" "destructive=False" "unpushed + amend → is_destructive False"
ok "classify_amend: unpushed amend allowed"

# ── CLI: exit codes match verdict ──────────────────────────────────────

set +e
"$PY" "$SHARED_SCRIPTS/amend_safety.py" "$(py_path "$repo_noremote")" "git commit --amend" >/dev/null 2>&1
rc_unpushed=$?
"$PY" "$SHARED_SCRIPTS/amend_safety.py" "$(py_path "$repo_pushed")" "git commit --amend" >/dev/null 2>&1
rc_pushed=$?
"$PY" "$SHARED_SCRIPTS/amend_safety.py" "$(py_path "$repo_pushed")" "git status" >/dev/null 2>&1
rc_nonamend=$?
set -e

assert_exit_code "0" "$rc_unpushed" "CLI: unpushed amend exits 0"
assert_exit_code "1" "$rc_pushed" "CLI: pushed amend exits 1"
assert_exit_code "0" "$rc_nonamend" "CLI: non-amend exits 0"
ok "amend_safety CLI: exit codes match verdict"
