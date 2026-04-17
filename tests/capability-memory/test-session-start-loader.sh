#!/usr/bin/env bash
# Test: the capability-memory SessionStart hook loads the registry without error.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

HOOK="$PLUGINS_ROOT/capability-memory/hooks/session-start/load-capability-registry.sh"
assert_file_exists "$HOOK"

export CLAUDE_PLUGIN_ROOT="$PLUGINS_ROOT/capability-memory"

set +e
output="$(bash "$HOOK" 2>&1)"
rc=$?
set -e

assert_exit_code "0" "$rc" "SessionStart hook exit code"
assert_contains "$output" "Loaded registry" "status line printed"
assert_contains "$output" "10 hosts" "host count reported"
ok "SessionStart loader reports 10 hosts, exit 0"

# Loader is idempotent — run twice, same result.
set +e
output2="$(bash "$HOOK" 2>&1)"
rc2=$?
set -e
assert_exit_code "0" "$rc2" "second invocation exit code"
assert_contains "$output2" "10 hosts" "second invocation reports 10 hosts"
ok "SessionStart loader is idempotent"

# With a missing registry file, the loader should NOT crash the session —
# just report the missing file to stderr.
new_sandbox > /dev/null
fake_plugin_root="$SANDBOX/fake"
mkdir -p "$fake_plugin_root/state" "$fake_plugin_root/hooks/session-start"
cp "$HOOK" "$fake_plugin_root/hooks/session-start/load-capability-registry.sh"
chmod +x "$fake_plugin_root/hooks/session-start/load-capability-registry.sh"
export CLAUDE_PLUGIN_ROOT="$fake_plugin_root"
set +e
output3="$(bash "$fake_plugin_root/hooks/session-start/load-capability-registry.sh" 2>&1)"
rc3=$?
set -e
assert_exit_code "0" "$rc3" "missing-registry exit is 0 (fail-open)"
assert_contains "$output3" "Registry missing" "missing-registry warning on stderr"
ok "SessionStart loader fails open when registry is missing"
