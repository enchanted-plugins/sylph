#!/usr/bin/env bash
# Test: when W2 fires a boundary with confidence < SYLPH_BOUNDARY_CONFIDENCE_THRESHOLD
# (or uncertain:true), the hook must
#   1. still emit the sylph.task.boundary.detected event on boundary-events.jsonl
#   2. mark that event record with escalated:true
#   3. append a sylph.boundary.escalation.requested record to escalations.jsonl
#
# The drive: two edits on src/auth.py, followed by a context switch to docs/README.md
# after a 15-minute gap — that's the same pattern tests/boundary-segmenter/test-boundary-fires.sh
# uses to guarantee a boundary fires. Under default θ=0.55 the computed distance
# runs well above 0.6, so confidence (=1.0 - distance) lands below the 0.7 floor.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

HOOK="$PLUGINS_ROOT/boundary-segmenter/hooks/post-tool-use/boundary-segment.sh"
assert_file_exists "$HOOK"

# Sandbox mimicking the real product layout so the hook resolves SHARED/PY.
new_sandbox > /dev/null
fake_product="$SANDBOX/sylph-sim"
mkdir -p "$fake_product/plugins/boundary-segmenter/hooks/post-tool-use"
mkdir -p "$fake_product/plugins/boundary-segmenter/state"
cp "$HOOK" "$fake_product/plugins/boundary-segmenter/hooks/post-tool-use/boundary-segment.sh"
chmod +x "$fake_product/plugins/boundary-segmenter/hooks/post-tool-use/boundary-segment.sh"
ln -s "$REPO_ROOT/shared" "$fake_product/shared"
fake_plugin_root="$fake_product/plugins/boundary-segmenter"

export CLAUDE_PLUGIN_ROOT="$fake_plugin_root"
events="$fake_plugin_root/state/boundary-events.jsonl"
escalations="$fake_plugin_root/state/escalations.jsonl"
metrics="$fake_plugin_root/state/metrics.jsonl"

# Event 1: auth edit — no boundary.
payload_1='{"tool_name":"Edit","tool_input":{"file_path":"src/auth.py","old_string":"old","new_string":"def verify_token(t): return sha256(t)"},"timestamp":1700000000}'
printf '%s' "$payload_1" | bash "$fake_plugin_root/hooks/post-tool-use/boundary-segment.sh" || fail "hook should not error on event 1"

# Event 2: same file + close in time — cohesive, no boundary.
payload_2='{"tool_name":"Edit","tool_input":{"file_path":"src/auth.py","old_string":"sha256","new_string":"hmac_sha256"},"timestamp":1700000060}'
printf '%s' "$payload_2" | bash "$fake_plugin_root/hooks/post-tool-use/boundary-segment.sh" || fail "hook should not error on event 2"

# Event 3: context switch + 15-minute idle gap — boundary fires with very low confidence.
payload_3='{"tool_name":"Write","tool_input":{"file_path":"docs/README.md","content":"install package with pip for local development work"},"timestamp":1700000900}'
printf '%s' "$payload_3" | bash "$fake_plugin_root/hooks/post-tool-use/boundary-segment.sh" || fail "hook should not error on event 3"

# Boundary event must exist.
assert_file_exists "$events" "boundary-events.jsonl exists after context-switch"
boundary_lines=$(grep -c 'sylph.task.boundary.detected' "$events" || true)
assert_eq "$boundary_lines" "1" "exactly one boundary event emitted"

# The boundary event must carry escalated:true.
last_event="$(tail -n1 "$events")"
escalated="$(printf '%s' "$last_event" | jq -r '.escalated')"
assert_eq "$escalated" "true" "boundary event marked escalated:true (low-confidence path)"

# The event must still carry the numeric confidence we emit downstream.
confidence_val="$(printf '%s' "$last_event" | jq -r '.confidence')"
assert_ne "$confidence_val" "null" "boundary event carries a numeric confidence"
assert_ne "$confidence_val" "" "boundary event carries a non-empty confidence"

# The escalation feed must have exactly one matching record.
assert_file_exists "$escalations" "escalations.jsonl created on first escalation"
esc_lines=$(grep -c 'sylph.boundary.escalation.requested' "$escalations" || true)
assert_eq "$esc_lines" "1" "exactly one escalation record appended"

esc_record="$(tail -n1 "$escalations")"
esc_event="$(printf '%s' "$esc_record" | jq -r '.event')"
assert_eq "$esc_event" "sylph.boundary.escalation.requested" "escalation schema: event field"

esc_agent="$(printf '%s' "$esc_record" | jq -r '.agent')"
assert_eq "$esc_agent" "boundary-detector" "escalation targets the boundary-detector agent"

esc_ts="$(printf '%s' "$esc_record" | jq -r '.ts')"
assert_ne "$esc_ts" "null" "escalation carries a timestamp"
assert_ne "$esc_ts" "" "escalation timestamp non-empty"

esc_reason="$(printf '%s' "$esc_record" | jq -r '.reason')"
assert_contains "$esc_reason" "confidence" "reason code references confidence/uncertainty"

esc_cluster="$(printf '%s' "$esc_record" | jq -c '.cluster')"
assert_ne "$esc_cluster" "null" "escalation carries a cluster preview for the Opus agent"

ok "low-confidence boundary: escalated:true on event + escalation record on feed"
