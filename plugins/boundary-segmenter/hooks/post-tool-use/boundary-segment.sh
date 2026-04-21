#!/usr/bin/env bash
# boundary-segmenter PostToolUse(Edit|Write|MultiEdit) — the W2 hot path.
#
# Reads the hook payload, delegates to shared/scripts/boundary_segment.py, records the
# verdict to state/metrics.jsonl. If a boundary fires, also appends a structured
# event line for downstream plugins (branch-workflow, commit-intelligence,
# pr-lifecycle) to consume via state/boundary-events.jsonl.
#
# Never blocks: PostToolUse hooks that fail will be treated by Claude Code as
# advisory. We exit 0 regardless unless the hook contract demands otherwise.

set -euo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$(dirname "$(dirname "$0")")")}"
PRODUCT_ROOT="$(dirname "$(dirname "$PLUGIN_ROOT")")"
SHARED="$PRODUCT_ROOT/shared/scripts"
STATE_FILE="$PLUGIN_ROOT/state/boundary-clusters.json"
METRICS="$PLUGIN_ROOT/state/metrics.jsonl"
EVENTS="$PLUGIN_ROOT/state/boundary-events.jsonl"
ESCALATIONS="$PLUGIN_ROOT/state/escalations.jsonl"

mkdir -p "$(dirname "$STATE_FILE")"

# Source constants for WEAVER_ settings (may override thresholds).
if [[ -f "$PRODUCT_ROOT/shared/constants.sh" ]]; then
    # shellcheck source=/dev/null
    source "$PRODUCT_ROOT/shared/constants.sh"
fi

# Confidence floor below which a boundary is provisional and must be
# reviewed by the Opus boundary-detector agent before downstream plugins
# commit to any irreversible action. Honors env override per the
# product-wide WEAVER_* convention.
CONF_THRESHOLD="${WEAVER_BOUNDARY_CONFIDENCE_THRESHOLD:-0.7}"

# Atomic-append helper — the escalations feed is append-only, concurrent
# with other plugins that may be touching sibling state files.
if [[ -f "$SHARED/atomic_state.sh" ]]; then
    # shellcheck source=/dev/null
    source "$SHARED/atomic_state.sh"
fi

# Resolve Python — prefer python3, fall back to python (handles Windows Store stub).
PY=""
if command -v python3 >/dev/null 2>&1 && python3 -c "import sys; print(sys.version_info[0])" 2>/dev/null | grep -qE '^3$'; then
    PY="python3"
elif command -v python >/dev/null 2>&1 && python -c "import sys; print(sys.version_info[0])" 2>/dev/null | grep -qE '^3$'; then
    PY="python"
fi
[[ -z "$PY" ]] && exit 0  # no Python — fail-open

# Read payload from stdin, pass through to the segmenter.
payload="$(cat)"
[[ -z "$payload" ]] && exit 0

set +e
verdict="$(printf '%s' "$payload" | "$PY" "$SHARED/boundary_segment.py" "$STATE_FILE" 2>/dev/null)"
seg_exit=$?
set -e

# Record metric: every PostToolUse invocation. Distance + boundary outcome.
ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if command -v jq >/dev/null 2>&1 && [[ -n "$verdict" ]]; then
    boundary="$(printf '%s' "$verdict" | jq -r '.boundary // false')"
    distance="$(printf '%s' "$verdict" | jq -r '.distance // 0')"
    uncertain="$(printf '%s' "$verdict" | jq -r '.uncertain // false')"
    confidence="$(printf '%s' "$verdict" | jq -r '.confidence // 1')"

    printf '{"ts":"%s","event":"post_tool_use","boundary":%s,"distance":%s,"confidence":%s,"uncertain":%s,"seg_exit":%d}\n' \
        "$ts" "$boundary" "$distance" "$confidence" "$uncertain" "$seg_exit" \
        >> "$METRICS"

    # On boundary: append a structured event record for downstream consumers.
    if [[ "$boundary" == "true" ]]; then
        closed="$(printf '%s' "$verdict" | jq -c '.closed_cluster // null')"
        active="$(printf '%s' "$verdict" | jq -c '.active_cluster // null')"

        # Decide whether this boundary needs Opus judgment before any
        # downstream plugin treats it as authoritative. We escalate when
        # either (a) the confidence falls below the configured floor, or
        # (b) the distance landed in the ±uncertainty_band around θ (the
        # Python segmenter flags this as `uncertain:true`). The hook never
        # calls Opus itself — it leaves an escalation record for the
        # /weaver:review-boundary skill to pick up.
        escalated="false"
        if command -v awk >/dev/null 2>&1; then
            below_floor="$(awk -v c="$confidence" -v t="$CONF_THRESHOLD" 'BEGIN { print (c+0 < t+0) ? "true" : "false" }')"
        else
            # Pure-bash fallback: compare as strings with leading zero padding.
            # Good enough to route edge cases — awk is universally available
            # everywhere we ship, so this branch is informational.
            below_floor="false"
        fi
        if [[ "$below_floor" == "true" || "$uncertain" == "true" ]]; then
            escalated="true"
        fi

        printf '{"ts":"%s","event":"weaver.task.boundary.detected","closed_cluster":%s,"active_cluster":%s,"distance":%s,"confidence":%s,"uncertain":%s,"escalated":%s}\n' \
            "$ts" "$closed" "$active" "$distance" "$confidence" "$uncertain" "$escalated" \
            >> "$EVENTS"

        if [[ "$escalated" == "true" ]]; then
            # Fire reason mirrors the rule that tripped — informational
            # only, consumed by /weaver:review-boundary + the audit trail.
            reason="low_confidence"
            if [[ "$uncertain" == "true" && "$below_floor" != "true" ]]; then
                reason="uncertainty_band"
            elif [[ "$uncertain" == "true" && "$below_floor" == "true" ]]; then
                reason="low_confidence_and_uncertainty_band"
            fi

            escalation_record="$(printf '%s' "$verdict" | jq -c \
                --arg ts "$ts" \
                --arg event "weaver.boundary.escalation.requested" \
                --arg reason "$reason" \
                --arg agent "boundary-detector" \
                '{ts:$ts, event:$event, cluster:(.closed_cluster // .active_cluster // null), confidence:(.confidence // null), distance:(.distance // null), uncertain:(.uncertain // false), reason:$reason, agent:$agent}')"

            if [[ -n "$escalation_record" ]]; then
                if command -v atomic_append >/dev/null 2>&1; then
                    printf '%s\n' "$escalation_record" | atomic_append "$ESCALATIONS"
                else
                    mkdir -p "$(dirname "$ESCALATIONS")"
                    [[ -e "$ESCALATIONS" ]] || : > "$ESCALATIONS"
                    printf '%s\n' "$escalation_record" >> "$ESCALATIONS"
                fi
            fi
        fi
    fi
fi

exit 0
