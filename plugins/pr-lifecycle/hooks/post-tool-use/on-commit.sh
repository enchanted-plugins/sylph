#!/usr/bin/env bash
# pr-lifecycle PostToolUse(Bash) — W4 listener.
#
# Tails plugins/commit-intelligence/state/executed-commits.jsonl from this
# plugin's persisted byte offset. For each new `sylph.commit.committed`
# event, drafts a PR record (title, body, reviewer suggestions) and appends
# it to state/pending-prs.jsonl. The /sylph:pr skill picks up pending PRs
# on invocation.
#
# Architectural note — this listener reacts to *executed* commits, not
# boundary events. That one-step-further offset closes the
# boundary → branch → commit → PR chain (per CLAUDE.md Lifecycle table).
# The matcher is Bash (not Edit|Write|MultiEdit) because the signal is a
# successful `git commit` invocation; commit-intelligence's /sylph:commit
# skill appends to executed-commits.jsonl on each successful commit.
#
# Advisory-only contract (shared/conduct/hooks.md):
#   - Never blocks tool execution (always exits 0).
#   - Idempotent: re-running without new executed-commit events is a no-op.
#   - Silent by default, prints a short summary to stderr on action.
#   - No network calls from the hook — PR opening is skill-invoked.
#
# Option B architecture — event-file per stream. Upstream owns the feed
# (commit-intelligence/state/executed-commits.jsonl); each downstream
# listener (just pr-lifecycle for now) owns its offset.

set -euo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$(dirname "$(dirname "$0")")")}"
PRODUCT_ROOT="${SYLPH_HOME:-$(dirname "$(dirname "$PLUGIN_ROOT")")}"
SHARED="$PRODUCT_ROOT/shared/scripts"

EVENTS="$PRODUCT_ROOT/plugins/commit-intelligence/state/executed-commits.jsonl"
OFFSET_FILE="$PLUGIN_ROOT/state/listener-offset.json"
PENDING_PRS="$PLUGIN_ROOT/state/pending-prs.jsonl"
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

# Hook-local Python adapter — avoids `python - <<EOF` vs stdin-pipe issues.
HOOK_STATE="$SHARED/_hook_state.py"

# Nothing to do if the upstream feed is missing.
[[ -f "$EVENTS" ]] || exit 0

# Resolve Python (best-effort; record building uses jq only).
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

# Read only the bytes past last_offset.
if ! tail_bytes=$(dd if="$EVENTS" bs=1 skip="$last_offset" 2>/dev/null); then
    tail_bytes="$(tail -c +$((last_offset + 1)) "$EVENTS" 2>/dev/null || printf '')"
fi

# Build a minimal title/body from a commit message. /sylph:pr upgrades this
# with boundary-cluster + Raven V4 continuity when actually opening the PR.
# Title = first line of the message (truncated to 72 chars). Body = the full
# message plus a Sylph footer.
while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    if ! command -v jq >/dev/null 2>&1; then continue; fi

    # Advisory contract: a malformed feed line must never crash the hook.
    # jq on non-JSON exits 4/5; the `|| true` neutralizes that under pipefail.
    event_name="$(printf '%s' "$line" | jq -r '.event // empty' 2>/dev/null || true)"
    [[ "$event_name" != "sylph.commit.committed" ]] && continue

    branch="$(printf '%s' "$line" | jq -r '.branch // empty' 2>/dev/null || true)"
    sha="$(printf '%s' "$line" | jq -r '.sha // empty' 2>/dev/null || true)"
    message="$(printf '%s' "$line" | jq -r '.message // empty' 2>/dev/null || true)"
    source_draft_ts="$(printf '%s' "$line" | jq -r '.source_draft_ts // empty' 2>/dev/null || true)"

    # Title: first line of message, truncated to 72 chars.
    title="$(printf '%s' "$message" | awk 'NR==1{print; exit}')"
    if [[ ${#title} -gt 72 ]]; then
        title="${title:0:72}"
    fi
    [[ -z "$title" ]] && title="chore: sylph-drafted PR"

    # Body: simple draft that /sylph:pr will replace with the rich
    # PRDescription.from_cluster output. Keep it structured so a developer
    # reviewing pending-prs.jsonl directly can still use it.
    body_text="## What changed

- \`${sha:0:8}\` — ${title}

## Why

_PR draft queued by pr-lifecycle chain-listener. Full description will
be composed from W2 cluster state + Raven V4 continuity when
\`/sylph:pr\` is invoked._

---
*Drafted by [Sylph](https://github.com/enchanted-plugins/sylph) (W4 pr-lifecycle).*"

    record="$(jq -nc \
        --arg ts "$ts" \
        --arg event "sylph.pr.drafted" \
        --arg branch "$branch" \
        --arg sha "$sha" \
        --arg title "$title" \
        --arg body "$body_text" \
        --arg source_commit "$sha" \
        --arg source_draft_ts "$source_draft_ts" \
        --argjson source "$line" \
        '{ts:$ts, event:$event, branch:$branch, sha:$sha, title:$title, body:$body, reviewer_suggestions:[], source_commit:$source_commit, source_draft_ts:$source_draft_ts, source_event:$source, executed:false}')"

    # Hooks are advisory — tolerate append failures.
    set +e
    if [[ -n "$PY" && -f "$HOOK_STATE" ]]; then
        printf '%s' "$record" | "$PY" "$HOOK_STATE" append "$PENDING_PRS"
    else
        printf '%s' "$record" | atomic_append "$PENDING_PRS"
    fi
    set -e
    new_count=$((new_count + 1))

    # Metric per executed-commit processed.
    metric="$(jq -nc \
        --arg ts "$ts" \
        --arg event "w4.commit.observed" \
        --arg branch "$branch" \
        --arg sha "$sha" \
        '{ts:$ts, event:$event, branch:$branch, sha:$sha}')"
    set +e
    if [[ -n "$PY" && -f "$HOOK_STATE" ]]; then
        printf '%s' "$metric" | "$PY" "$HOOK_STATE" append "$METRICS"
    else
        printf '%s' "$metric" | atomic_append "$METRICS"
    fi
    set -e
done <<< "$tail_bytes"

# Persist new offset — last thing we do, tolerant of write errors.
set +e
if [[ -n "$PY" && -f "$HOOK_STATE" ]]; then
    printf '{"last_offset":%d,"updated_at":"%s"}' "$current_size" "$ts" \
        | "$PY" "$HOOK_STATE" write "$OFFSET_FILE"
else
    printf '{"last_offset":%d,"updated_at":"%s"}' "$current_size" "$ts" | atomic_write "$OFFSET_FILE"
fi
set -e

if (( new_count > 0 )); then
    printf 'sylph[pr-lifecycle]: %d commit event(s) drafted → pending-prs.jsonl\n' "$new_count" >&2
fi

exit 0
