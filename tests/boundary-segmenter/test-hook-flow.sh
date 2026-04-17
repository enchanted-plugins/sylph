#!/usr/bin/env bash
# Test: the PostToolUse(Edit|Write) hook drives the segmenter end-to-end and
# writes both metrics.jsonl and boundary-events.jsonl with correct structure.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

HOOK="$PLUGINS_ROOT/boundary-segmenter/hooks/post-tool-use/boundary-segment.sh"
assert_file_exists "$HOOK"

# Sandbox mimicking the real product layout so the hook can resolve SHARED/PY.
new_sandbox > /dev/null
fake_product="$SANDBOX/weaver-sim"
mkdir -p "$fake_product/plugins/boundary-segmenter/hooks/post-tool-use"
mkdir -p "$fake_product/plugins/boundary-segmenter/state"
cp "$HOOK" "$fake_product/plugins/boundary-segmenter/hooks/post-tool-use/boundary-segment.sh"
chmod +x "$fake_product/plugins/boundary-segmenter/hooks/post-tool-use/boundary-segment.sh"
ln -s "$REPO_ROOT/shared" "$fake_product/shared"
fake_plugin_root="$fake_product/plugins/boundary-segmenter"

export CLAUDE_PLUGIN_ROOT="$fake_plugin_root"
metrics="$fake_plugin_root/state/metrics.jsonl"
events="$fake_plugin_root/state/boundary-events.jsonl"
clusters="$fake_plugin_root/state/boundary-clusters.json"

# Event 1: auth edit.
payload_1='{"tool_name":"Edit","tool_input":{"file_path":"src/auth.py","old_string":"old","new_string":"def verify_token(t): return sha256(t)"},"timestamp":1700000000}'
set +e
printf '%s' "$payload_1" | bash "$fake_plugin_root/hooks/post-tool-use/boundary-segment.sh"
rc=$?
set -e
assert_exit_code "0" "$rc" "hook exit on first event"
assert_file_exists "$metrics" "metrics.jsonl created"
assert_file_exists "$clusters" "clusters.json created"
assert_jq "$metrics" '.boundary' "false" "first event: no boundary"
ok "event 1: cluster opens, no boundary, metrics recorded"

# Event 2: context switch → boundary.
payload_2='{"tool_name":"Write","tool_input":{"file_path":"docs/README.md","content":"install package with pip for local development work"},"timestamp":1700000900}'
set +e
printf '%s' "$payload_2" | bash "$fake_plugin_root/hooks/post-tool-use/boundary-segment.sh"
rc=$?
set -e
assert_exit_code "0" "$rc" "hook exit on second event"
assert_file_exists "$events" "boundary-events.jsonl created on boundary"

# Read the latest metrics record.
last_metric="$(tail -n1 "$metrics")"
boundary_fired="$(printf '%s' "$last_metric" | jq -r '.boundary')"
assert_eq "$boundary_fired" "true" "second event fires a boundary"

# Read the boundary event.
last_event="$(tail -n1 "$events")"
event_name="$(printf '%s' "$last_event" | jq -r '.event')"
assert_eq "$event_name" "weaver.task.boundary.detected" "boundary event schema"

closed_files="$(printf '%s' "$last_event" | jq -r '.closed_cluster.events[0].files[0]')"
assert_eq "$closed_files" "src/auth.py" "closed cluster references original file"
ok "event 2: boundary fires, events.jsonl records weaver.task.boundary.detected"
