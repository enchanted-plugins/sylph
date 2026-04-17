#!/usr/bin/env bash
# Test: the PreToolUse(Bash) hook script itself — payload in stdin, exit codes out,
# audit log records the attempt. Covers the full decoder path (jq → python → audit).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

HOOK="$PLUGINS_ROOT/weaver-gate/hooks/pre-tool-use/inspect-git-command.sh"
assert_file_exists "$HOOK" "gate hook script"

# Use a sandboxed CLAUDE_PLUGIN_ROOT so the audit log goes to a tmp state dir.
new_sandbox > /dev/null
fake_plugin_root="$SANDBOX/plugin"
mkdir -p "$fake_plugin_root/hooks/pre-tool-use" "$fake_plugin_root/state"
# Symlink the real hook into the fake plugin root so path derivations work.
cp "$HOOK" "$fake_plugin_root/hooks/pre-tool-use/inspect-git-command.sh"
chmod +x "$fake_plugin_root/hooks/pre-tool-use/inspect-git-command.sh"

# The hook derives PRODUCT_ROOT by climbing two dirs — so we also need to point
# it at the real shared/scripts via CLAUDE_PLUGIN_ROOT trick. Simpler: just
# override SHARED by pre-pointing to real structure. We'll instead stage a
# nested sandbox matching the real layout.
rm -rf "$fake_plugin_root"
fake_product="$SANDBOX/weaver-sim"
mkdir -p "$fake_product/plugins/weaver-gate/hooks/pre-tool-use"
mkdir -p "$fake_product/plugins/weaver-gate/state"
cp "$HOOK" "$fake_product/plugins/weaver-gate/hooks/pre-tool-use/inspect-git-command.sh"
chmod +x "$fake_product/plugins/weaver-gate/hooks/pre-tool-use/inspect-git-command.sh"
ln -s "$REPO_ROOT/shared" "$fake_product/shared"
fake_plugin_root="$fake_product/plugins/weaver-gate"
audit="$fake_plugin_root/state/audit.jsonl"

export CLAUDE_PLUGIN_ROOT="$fake_plugin_root"

# Case 1: safe command → exit 0, audit records verdict_exit=0.
rm -f "$audit"
set +e
output="$(printf '%s' '{"tool_input":{"command":"git status"}}' | bash "$fake_plugin_root/hooks/pre-tool-use/inspect-git-command.sh" 2>&1)"
rc=$?
set -e
assert_exit_code "0" "$rc" "safe command exit code"
assert_file_exists "$audit" "audit log written"
assert_jq "$audit" '.verdict_exit' "0" "safe audit records exit 0"
assert_jq "$audit" '.op' "status" "safe audit records op 'status'"
ok "safe command: exit 0, audit recorded"

# Case 2: destructive command → exit 2, audit records verdict_exit=1, recovery days set.
rm -f "$audit"
set +e
output="$(printf '%s' '{"tool_input":{"command":"git push --force origin main"}}' | bash "$fake_plugin_root/hooks/pre-tool-use/inspect-git-command.sh" 2>&1)"
rc=$?
set -e
assert_exit_code "2" "$rc" "destructive command blocks with exit 2"
assert_jq "$audit" '.verdict_exit' "1" "destructive audit records exit 1"
assert_jq "$audit" '.op' "git push --force" "destructive audit records op"
assert_jq "$audit" '.recovery_days' "30" "destructive audit records recovery window"
assert_contains "$output" "Destructive git operation detected" "stderr surfaces the block reason"
ok "destructive command: exit 2, audit + stderr OK"

# Case 3: protected-destructive → exit 2, audit records verdict_exit=2.
rm -f "$audit"
set +e
output="$(printf '%s' '{"tool_input":{"command":"git clean -fdx"}}' | bash "$fake_plugin_root/hooks/pre-tool-use/inspect-git-command.sh" 2>&1)"
rc=$?
set -e
assert_exit_code "2" "$rc" "protected-destructive blocks with exit 2"
assert_jq "$audit" '.verdict_exit' "2" "protected-destructive audit records exit 2"
assert_jq "$audit" '.op' "git clean -fdx" "protected-destructive audit records op"
assert_jq "$audit" '.recovery_days' "0" "protected-destructive recovery = 0 (irrecoverable)"
ok "protected-destructive: exit 2, audit + stderr OK"

# Case 4: non-git → exit 0, NO audit record (short-circuit before classification).
rm -f "$audit"
set +e
printf '%s' '{"tool_input":{"command":"ls -la"}}' | bash "$fake_plugin_root/hooks/pre-tool-use/inspect-git-command.sh" 2>&1
rc=$?
set -e
assert_exit_code "0" "$rc" "non-git command exit 0"
if [[ -f "$audit" ]]; then
    fail "non-git command should not write audit log"
fi
ok "non-git command: exit 0, no audit record (short-circuit)"
