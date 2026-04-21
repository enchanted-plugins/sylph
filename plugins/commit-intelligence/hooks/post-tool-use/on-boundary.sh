#!/usr/bin/env bash
# commit-intelligence PostToolUse(Edit|Write|MultiEdit) — W1 listener.
#
# Tails plugins/boundary-segmenter/state/boundary-events.jsonl from this
# plugin's persisted byte offset. For each new `weaver.task.boundary.detected`
# event, derives a Conventional-Commits type hint from the closed cluster's
# file paths + edit signatures, and appends a draft record to
# state/pending-drafts.jsonl. The /weaver:commit skill (Sonnet drafter) picks
# up pending drafts on invocation.
#
# Advisory-only contract:
#   - Never blocks tool execution (always exits 0).
#   - Idempotent: re-running without new events is a no-op.
#   - No LLM call from the hook — drafting is skill-invoked.
#
# Option 1 architecture — independent listener; owns its own offset.

set -euo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$(dirname "$(dirname "$0")")")}"
PRODUCT_ROOT="${WEAVER_HOME:-$(dirname "$(dirname "$PLUGIN_ROOT")")}"
SHARED="$PRODUCT_ROOT/shared/scripts"

EVENTS="$PRODUCT_ROOT/plugins/boundary-segmenter/state/boundary-events.jsonl"
OFFSET_FILE="$PLUGIN_ROOT/state/listener-offset.json"
PENDING="$PLUGIN_ROOT/state/pending-drafts.jsonl"
METRICS="$PLUGIN_ROOT/state/metrics.jsonl"

mkdir -p "$PLUGIN_ROOT/state"

if [[ -f "$SHARED/atomic_state.sh" ]]; then
    # shellcheck source=/dev/null
    source "$SHARED/atomic_state.sh"
else
    exit 0
fi

# Hook-local Python adapter — see branch-workflow for rationale.
HOOK_STATE="$SHARED/_hook_state.py"

PY=""
if command -v python3 >/dev/null 2>&1 && python3 -c "import sys" 2>/dev/null; then
    PY="python3"
elif command -v python >/dev/null 2>&1 && python -c "import sys" 2>/dev/null; then
    PY="python"
fi

[[ -f "$EVENTS" ]] || exit 0

last_offset=0
if [[ -f "$OFFSET_FILE" ]]; then
    if command -v jq >/dev/null 2>&1; then
        last_offset="$(jq -r '.last_offset // 0' "$OFFSET_FILE" 2>/dev/null || printf '0')"
    fi
fi

current_size=$(wc -c < "$EVENTS" | tr -d '[:space:]')
[[ -z "$current_size" ]] && current_size=0

if (( current_size <= last_offset )); then
    exit 0
fi

ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
new_count=0

if ! tail_bytes=$(dd if="$EVENTS" bs=1 skip="$last_offset" 2>/dev/null); then
    tail_bytes="$(tail -c +$((last_offset + 1)) "$EVENTS" 2>/dev/null || printf '')"
fi

# Infer Conventional-Commits type from path heuristics — cheap, deterministic
# fallback when no LLM is available. Matches the canonical type set from
# shared/scripts/commit_classify.py (feat, fix, docs, style, refactor, perf,
# test, build, ci, chore, revert).
infer_type() {
    local files="$1"
    local f
    while IFS= read -r f; do
        [[ -z "$f" ]] && continue
        case "$f" in
            docs/*|*.md|*.rst|*.txt|README*|CHANGELOG*|LICENSE*)
                printf 'docs'; return ;;
            tests/*|test/*|*_test.*|*.test.*|*.spec.*)
                printf 'test'; return ;;
            .github/workflows/*|.gitlab-ci.yml|.circleci/*|Jenkinsfile|.drone.yml|.buildkite/*)
                printf 'ci'; return ;;
            Dockerfile*|*.dockerfile|Makefile|*.mk|package.json|package-lock.json|pyproject.toml|requirements*.txt|Cargo.toml|go.mod|build.gradle*|pom.xml)
                printf 'build'; return ;;
        esac
    done <<< "$files"
    # Default for source edits is `feat`; the Sonnet drafter re-classifies.
    printf 'feat'
}

while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    if ! command -v jq >/dev/null 2>&1; then continue; fi

    event_name="$(printf '%s' "$line" | jq -r '.event // empty' 2>/dev/null)"
    [[ "$event_name" != "weaver.task.boundary.detected" ]] && continue

    files_json="$(printf '%s' "$line" | jq -c '[.closed_cluster.events[]?.files[]?] | unique' 2>/dev/null || printf '[]')"
    files_raw="$(printf '%s' "$line" | jq -r '[.closed_cluster.events[]?.files[]?] | unique | .[]' 2>/dev/null || true)"

    commit_type="$(infer_type "$files_raw")"

    # Slug seed from first file path.
    dominant_file="$(printf '%s\n' "$files_raw" | head -n1)"
    [[ -z "$dominant_file" ]] && dominant_file=""

    # Event count in the closed cluster (drives commit-body bullet count).
    event_count="$(printf '%s' "$line" | jq -r '.closed_cluster.events | length // 0' 2>/dev/null || printf '0')"

    record="$(jq -nc \
        --arg ts "$ts" \
        --arg event "commit.drafted" \
        --arg type "$commit_type" \
        --arg file "$dominant_file" \
        --argjson files "$files_json" \
        --argjson event_count "$event_count" \
        --argjson source "$line" \
        '{ts:$ts, event:$event, suggested_type:$type, dominant_file:$file, files:$files, event_count:$event_count, source_event:$source, executed:false}')"

    set +e
    if [[ -n "$PY" && -f "$HOOK_STATE" ]]; then
        printf '%s' "$record" | "$PY" "$HOOK_STATE" append "$PENDING"
    else
        printf '%s' "$record" | atomic_append "$PENDING"
    fi
    set -e
    new_count=$((new_count + 1))

    metric="$(jq -nc \
        --arg ts "$ts" \
        --arg event "w1.boundary.observed" \
        --arg type "$commit_type" \
        --argjson files "$event_count" \
        '{ts:$ts, event:$event, suggested_type:$type, cluster_event_count:$files}')"
    set +e
    if [[ -n "$PY" && -f "$HOOK_STATE" ]]; then
        printf '%s' "$metric" | "$PY" "$HOOK_STATE" append "$METRICS"
    else
        printf '%s' "$metric" | atomic_append "$METRICS"
    fi
    set -e
done <<< "$tail_bytes"

set +e
if [[ -n "$PY" && -f "$HOOK_STATE" ]]; then
    printf '{"last_offset":%d,"updated_at":"%s"}' "$current_size" "$ts" \
        | "$PY" "$HOOK_STATE" write "$OFFSET_FILE"
else
    printf '{"last_offset":%d,"updated_at":"%s"}' "$current_size" "$ts" | atomic_write "$OFFSET_FILE"
fi
set -e

if (( new_count > 0 )); then
    printf 'weaver[commit-intelligence]: %d boundary event(s) drafted → pending-drafts.jsonl\n' "$new_count" >&2
fi

exit 0
