#!/usr/bin/env bash
# branch-workflow PostToolUse(Edit|Write|MultiEdit) — W3 listener.
#
# Tails plugins/boundary-segmenter/state/boundary-events.jsonl from this
# plugin's persisted byte offset. For each new `sylph.task.boundary.detected`
# event, runs the W3 workflow classifier and appends a "branch-suggested"
# record to state/pending-actions.jsonl. Auto-detection on; auto-execution
# gated (the /sylph:branch skill picks up pending actions).
#
# Advisory-only contract (shared/conduct/hooks.md):
#   - Never blocks tool execution (always exits 0).
#   - Idempotent: re-running without new events is a no-op.
#   - Silent by default, prints a short summary to stderr on action.
#
# Option 1 architecture (independent listeners): each downstream plugin owns
# its own offset. Reason — closer to the event-bus model the family targets;
# loose coupling over deterministic fire order.

set -euo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$(dirname "$(dirname "$0")")")}"
PRODUCT_ROOT="${SYLPH_HOME:-$(dirname "$(dirname "$PLUGIN_ROOT")")}"
SHARED="$PRODUCT_ROOT/shared/scripts"

EVENTS="$PRODUCT_ROOT/plugins/boundary-segmenter/state/boundary-events.jsonl"
OFFSET_FILE="$PLUGIN_ROOT/state/listener-offset.json"
PENDING="$PLUGIN_ROOT/state/pending-actions.jsonl"
METRICS="$PLUGIN_ROOT/state/metrics.jsonl"

mkdir -p "$PLUGIN_ROOT/state"

# Source the shared atomic-state bash wrapper.
if [[ -f "$SHARED/atomic_state.sh" ]]; then
    # shellcheck source=/dev/null
    source "$SHARED/atomic_state.sh"
else
    # atomic_state.sh missing — fail-open per advisory-only contract.
    exit 0
fi

# Hook-local Python adapter — shared/scripts/_hook_state.py wraps
# atomic_state.{append_jsonl, write_state}. Using a script file (not an inline
# heredoc) avoids the `python - <<EOF` vs stdin-pipe collision.
HOOK_STATE="$SHARED/_hook_state.py"

# Nothing to do if the upstream feed is missing.
[[ -f "$EVENTS" ]] || exit 0

# Resolve Python for W3 classification.
PY=""
if command -v python3 >/dev/null 2>&1 && python3 -c "import sys" 2>/dev/null; then
    PY="python3"
elif command -v python >/dev/null 2>&1 && python -c "import sys" 2>/dev/null; then
    PY="python"
fi

# Read last-seen byte offset (default 0).
last_offset=0
if [[ -f "$OFFSET_FILE" ]]; then
    if command -v jq >/dev/null 2>&1; then
        last_offset="$(jq -r '.last_offset // 0' "$OFFSET_FILE" 2>/dev/null || printf '0')"
    fi
fi

# Current file size.
current_size=$(wc -c < "$EVENTS" | tr -d '[:space:]')
[[ -z "$current_size" ]] && current_size=0

# Nothing new to process.
if (( current_size <= last_offset )); then
    exit 0
fi

ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
new_count=0

# Read only the bytes past last_offset, split into lines.
# dd is portable across busybox/coreutils; fall back to tail -c if dd stumbles.
if ! tail_bytes=$(dd if="$EVENTS" bs=1 skip="$last_offset" 2>/dev/null); then
    tail_bytes="$(tail -c +$((last_offset + 1)) "$EVENTS" 2>/dev/null || printf '')"
fi

while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    if ! command -v jq >/dev/null 2>&1; then continue; fi

    event_name="$(printf '%s' "$line" | jq -r '.event // empty' 2>/dev/null)"
    [[ "$event_name" != "sylph.task.boundary.detected" ]] && continue

    # Extract slug hint from the closed cluster's dominant file path.
    files_raw="$(printf '%s' "$line" | jq -r '[.closed_cluster.events[]?.files[]?] | unique | .[]' 2>/dev/null || true)"
    dominant_file="$(printf '%s\n' "$files_raw" | head -n1)"
    [[ -z "$dominant_file" ]] && dominant_file="unknown"

    # Classify workflow — advisory, best-effort. Fail-open on any error.
    workflow_label="unknown"
    workflow_confidence="0"
    if [[ -n "$PY" && -f "$SHARED/workflow_detect.py" ]]; then
        set +e
        classify_json="$("$PY" "$SHARED/workflow_detect.py" detect 2>/dev/null)"
        set -e
        if [[ -n "$classify_json" ]] && command -v jq >/dev/null 2>&1; then
            workflow_label="$(printf '%s' "$classify_json" | jq -r '.workflow.label // "unknown"' 2>/dev/null || printf 'unknown')"
            workflow_confidence="$(printf '%s' "$classify_json" | jq -r '.workflow.confidence // 0' 2>/dev/null || printf '0')"
        fi
    fi

    # Build the pending-action record. /sylph:branch consumes this.
    record="$(jq -nc \
        --arg ts "$ts" \
        --arg event "branch.suggested" \
        --arg workflow "$workflow_label" \
        --arg file "$dominant_file" \
        --argjson confidence "$workflow_confidence" \
        --argjson source "$line" \
        '{ts:$ts, event:$event, workflow:$workflow, dominant_file:$file, confidence:$confidence, source_event:$source, executed:false}')"

    # Hooks are advisory — tolerate append failures. Prefer the Python
    # helper (works cross-platform); fall back to the bash wrapper.
    set +e
    if [[ -n "$PY" && -f "$HOOK_STATE" ]]; then
        printf '%s' "$record" | "$PY" "$HOOK_STATE" append "$PENDING"
    else
        printf '%s' "$record" | atomic_append "$PENDING"
    fi
    set -e
    new_count=$((new_count + 1))

    # Metric per boundary processed.
    metric="$(jq -nc \
        --arg ts "$ts" \
        --arg event "w3.boundary.observed" \
        --arg workflow "$workflow_label" \
        --argjson confidence "$workflow_confidence" \
        '{ts:$ts, event:$event, workflow:$workflow, confidence:$confidence}')"
    set +e
    if [[ -n "$PY" && -f "$HOOK_STATE" ]]; then
        printf '%s' "$metric" | "$PY" "$HOOK_STATE" append "$METRICS"
    else
        printf '%s' "$metric" | atomic_append "$METRICS"
    fi
    set -e
done <<< "$tail_bytes"

# Persist new offset — last thing we do, again tolerant of write errors.
set +e
if [[ -n "$PY" && -f "$HOOK_STATE" ]]; then
    printf '{"last_offset":%d,"updated_at":"%s"}' "$current_size" "$ts" \
        | "$PY" "$HOOK_STATE" write "$OFFSET_FILE"
else
    printf '{"last_offset":%d,"updated_at":"%s"}' "$current_size" "$ts" | atomic_write "$OFFSET_FILE"
fi
set -e

if (( new_count > 0 )); then
    printf 'sylph[branch-workflow]: %d boundary event(s) processed → pending-actions.jsonl\n' "$new_count" >&2
fi

exit 0
