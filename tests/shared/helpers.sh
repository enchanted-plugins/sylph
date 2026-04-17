#!/usr/bin/env bash
# Shared test helpers for Weaver test suite.
#
# Sourced by every test-*.sh script. Provides:
#   - REPO_ROOT, SHARED_SCRIPTS, PY (resolved once)
#   - Assertion DSL: assert_eq, assert_ne, assert_contains, assert_exit_code,
#     assert_jq, assert_json_valid, fail
#   - Sandbox helpers: new_sandbox, mock_git_repo, cleanup
#
# Conventions:
#   - Every test script MUST `set -euo pipefail` before sourcing.
#   - Every test MUST clean up its sandbox on EXIT via the provided trap.
#   - Assertions print to stderr on failure and exit 1.

# Caller guard: don't allow executing this directly.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "helpers.sh is a library — source it, don't execute it" >&2
    exit 2
fi

# ── Paths ─────────────────────────────────────────────────────────────

HELPER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TESTS_ROOT="$(cd "$HELPER_DIR/.." && pwd)"
REPO_ROOT="$(cd "$TESTS_ROOT/.." && pwd)"
SHARED_SCRIPTS="$REPO_ROOT/shared/scripts"
PLUGINS_ROOT="$REPO_ROOT/plugins"

# Python-safe absolute paths.
# Under MSYS/Git-Bash on Windows the shell sees `/c/foo/bar` but Python
# (native CPython) needs `C:/foo/bar` for sys.path + filesystem access.
# `cygpath -m` returns the mixed Windows form with forward slashes.
py_path() {
    local p="$1"
    if command -v cygpath >/dev/null 2>&1; then
        cygpath -m "$p"
    else
        printf '%s' "$p"
    fi
}

SHARED_SCRIPTS_PY="$(py_path "$SHARED_SCRIPTS")"
REPO_ROOT_PY="$(py_path "$REPO_ROOT")"
PLUGINS_ROOT_PY="$(py_path "$PLUGINS_ROOT")"

# Resolve Python once — prefer python3, fall back to python on Windows.
resolve_python() {
    local py=""
    if command -v python3 >/dev/null 2>&1 && python3 -c "import sys; print(sys.version_info[0])" 2>/dev/null | grep -qE '^3$'; then
        py="python3"
    elif command -v python >/dev/null 2>&1 && python -c "import sys; print(sys.version_info[0])" 2>/dev/null | grep -qE '^3$'; then
        py="python"
    fi
    printf '%s' "$py"
}

PY="$(resolve_python)"
if [[ -z "$PY" ]]; then
    echo "FATAL: no usable Python 3 on PATH" >&2
    exit 2
fi

# ── Sandbox ───────────────────────────────────────────────────────────

SANDBOX=""

new_sandbox() {
    SANDBOX="$(mktemp -d)"
    # shellcheck disable=SC2064
    trap "cleanup_sandbox" EXIT
    printf '%s' "$SANDBOX"
}

cleanup_sandbox() {
    if [[ -n "${SANDBOX:-}" && -d "$SANDBOX" ]]; then
        rm -rf "$SANDBOX"
    fi
}

mock_git_repo() {
    # Creates a minimal git repo in a fresh sandbox and echoes its path.
    local dir
    dir="$(mktemp -d)"
    (
        cd "$dir"
        git init -q -b main
        git config user.email "test@weaver.local"
        git config user.name "weaver-test"
        echo "# test" > README.md
        git add README.md
        git commit -q -m "chore: seed"
    ) >/dev/null
    printf '%s' "$dir"
}

# ── Assertion DSL ─────────────────────────────────────────────────────

_fail_count=0
_test_name="${0##*/}"

fail() {
    local msg="$*"
    echo "  ASSERT FAIL in $_test_name: $msg" >&2
    _fail_count=$((_fail_count + 1))
    exit 1
}

assert_eq() {
    local actual="$1" expected="$2" msg="${3:-values differ}"
    if [[ "$actual" != "$expected" ]]; then
        fail "$msg
    expected: $expected
    actual:   $actual"
    fi
}

assert_ne() {
    local actual="$1" forbidden="$2" msg="${3:-values should differ}"
    if [[ "$actual" == "$forbidden" ]]; then
        fail "$msg (both were: $actual)"
    fi
}

assert_contains() {
    local haystack="$1" needle="$2" msg="${3:-substring not found}"
    if [[ "$haystack" != *"$needle"* ]]; then
        fail "$msg
    haystack: $haystack
    needle:   $needle"
    fi
}

assert_not_contains() {
    local haystack="$1" needle="$2" msg="${3:-substring unexpectedly present}"
    if [[ "$haystack" == *"$needle"* ]]; then
        fail "$msg
    haystack: $haystack
    forbidden: $needle"
    fi
}

assert_exit_code() {
    local expected="$1" actual="$2" msg="${3:-exit code differs}"
    if [[ "$actual" != "$expected" ]]; then
        fail "$msg
    expected exit: $expected
    actual exit:   $actual"
    fi
}

assert_file_exists() {
    local path="$1" msg="${2:-file missing}"
    if [[ ! -f "$path" ]]; then
        fail "$msg: $path"
    fi
}

assert_json_valid() {
    local path="$1" msg="${2:-invalid JSON}"
    if ! jq empty "$path" >/dev/null 2>&1; then
        fail "$msg: $path"
    fi
}

assert_jq() {
    # assert_jq <file> <jq-filter> <expected> [msg]
    local path="$1" filter="$2" expected="$3" msg="${4:-jq filter mismatch}"
    local actual
    actual="$(jq -r "$filter" "$path" 2>&1)"
    if [[ "$actual" != "$expected" ]]; then
        fail "$msg
    filter:   $filter
    expected: $expected
    actual:   $actual"
    fi
}

# ── One-liner: declare a test passed ──────────────────────────────────

ok() {
    echo "  ok  $*"
}
