#!/usr/bin/env bash
# Weaver test runner — runs every test-*.sh under tests/<plugin>/, reports
# pass/fail per plugin + totals.
#
# Exit 0 iff every test passes. Nonzero with count otherwise.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PASS=0
FAIL=0
ERRORS=()

run_test() {
    local test_file="$1"
    local test_name
    test_name=$(basename "$test_file" .sh)
    local dir_name
    dir_name=$(basename "$(dirname "$test_file")")

    printf "  %-22s %-45s " "$dir_name" "$test_name"

    local output
    output=$(bash "$test_file" 2>&1)
    local exit_code=$?

    if [[ $exit_code -eq 0 ]]; then
        printf "[\033[32mPASS\033[0m]\n"
        PASS=$((PASS + 1))
    else
        printf "[\033[31mFAIL\033[0m]\n"
        FAIL=$((FAIL + 1))
        ERRORS+=("$dir_name/$test_name (exit $exit_code):
$output")
    fi
}

printf '\n'
printf '══════════════════════════════════════════════════════════════\n'
printf ' WEAVER TEST SUITE\n'
printf '══════════════════════════════════════════════════════════════\n'
printf '\n'

# Iterate plugin subdirs in a stable order.
for plugin_dir in "$SCRIPT_DIR"/*/; do
    plugin_name=$(basename "$plugin_dir")
    # Skip the shared helper dir — it's not a test suite itself.
    if [[ "$plugin_name" == "shared" ]]; then continue; fi

    # Collect test files; skip empty dirs silently.
    shopt -s nullglob
    tests=("$plugin_dir"/test-*.sh)
    shopt -u nullglob
    if [[ "${#tests[@]}" -eq 0 ]]; then continue; fi

    for test_file in "${tests[@]}"; do
        run_test "$test_file"
    done
done

printf '\n'
printf '──────────────────────────────────────────────────────────────\n'
printf '  Passed: \033[32m%d\033[0m    Failed: \033[31m%d\033[0m    Total: %d\n' "$PASS" "$FAIL" "$((PASS + FAIL))"
printf '──────────────────────────────────────────────────────────────\n'

if [[ "$FAIL" -gt 0 ]]; then
    printf '\nFailures:\n'
    for err in "${ERRORS[@]}"; do
        printf '\n%s\n' "──────────────────────────────────────────────────────────────"
        printf '%s\n' "$err"
    done
    exit 1
fi

exit 0
