#!/usr/bin/env bash
# weaver-gate PreToolUse(Bash) — destructive-op decision-gate.
#
# Reads a PreToolUse payload from stdin (Claude Code hook protocol), extracts
# the Bash command, and delegates classification to shared/scripts/destructive_patterns.py.
#
# Exit semantics follow Claude Code's hook contract:
#   0 — allow the tool call to proceed
#   2 — block with reason, surface decision-gate prompt to Claude
# Anything else — allow (fail-open so a hook bug never stops the user's work).
#
# Dependencies: bash, jq, python3. All shipped by default with Git-for-Windows,
# macOS, and every major Linux distro. Zero pip installs.

set -euo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$(dirname "$(dirname "$0")")")}"
PRODUCT_ROOT="$(dirname "$(dirname "$PLUGIN_ROOT")")"
SHARED="$PRODUCT_ROOT/shared/scripts"
AUDIT_LOG="$PLUGIN_ROOT/state/audit.jsonl"

mkdir -p "$(dirname "$AUDIT_LOG")"

# Read the full hook payload from stdin.
payload="$(cat)"

# Extract the Bash command. If jq is missing or payload isn't what we expect,
# fail-open.
command -v jq >/dev/null 2>&1 || exit 0

# Resolve Python interpreter. On Windows, `python3` may resolve to a
# Microsoft Store stub that exits 49 without running anything; prefer
# the real `python` if it's a CPython distribution.
PY=""
if command -v python3 >/dev/null 2>&1; then
    # Quick probe: does python3 actually print a version? (Store stub prints stderr only.)
    if python3 -c "import sys; print(sys.version_info[0])" 2>/dev/null | grep -qE '^3$'; then
        PY="python3"
    fi
fi
if [[ -z "$PY" ]] && command -v python >/dev/null 2>&1; then
    if python -c "import sys; print(sys.version_info[0])" 2>/dev/null | grep -qE '^3$'; then
        PY="python"
    fi
fi
[[ -z "$PY" ]] && exit 0  # no usable Python — fail-open

cmd="$(printf '%s' "$payload" | jq -r '.tool_input.command // empty' 2>/dev/null || true)"
[[ -z "$cmd" ]] && exit 0

# Only care about git invocations. Short-circuit everything else.
[[ "$cmd" =~ (^|[[:space:]])git([[:space:]]|$) ]] || exit 0

# Classify. Python exits 0 (safe), 1 (destructive), 2 (protected-destructive).
# Capture stdout first, then run a second invocation purely for the exit code.
# Two calls is wasteful but idempotent; the simpler `$(...)` + `$?` pattern
# collides with `set -e` / `||` semantics and silently drops the code.
set +e
verdict="$("$PY" "$SHARED/destructive_patterns.py" "$cmd" 2>/dev/null)"
"$PY" "$SHARED/destructive_patterns.py" "$cmd" >/dev/null 2>&1
exit_code=$?
set -e

# Parse verdict JSON for audit log and user-facing reason.
op="$(printf '%s' "$verdict"     | jq -r '.op // "unknown"'     2>/dev/null || echo unknown)"
reason="$(printf '%s' "$verdict" | jq -r '.reason // "unknown"' 2>/dev/null || echo unknown)"
recovery="$(printf '%s' "$verdict" | jq -r '.recovery_window_days // 0' 2>/dev/null || echo 0)"

# Append audit record regardless of outcome.
ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '{"ts":"%s","op":"%s","cmd":%s,"verdict_exit":%d,"recovery_days":%s}\n' \
    "$ts" "$op" "$(printf '%s' "$cmd" | jq -Rs .)" "$exit_code" "$recovery" \
    >> "$AUDIT_LOG"

# Safe → allow silently.
if [[ "$exit_code" -eq 0 ]]; then
    exit 0
fi

# Destructive or protected-destructive → block (exit 2).
# Claude Code surfaces the stderr message as the block reason, which reaches
# the model context. The model then decides whether to proceed after the
# decision-gate skill fires.
cat <<EOF >&2
[weaver-gate] Destructive git operation detected.

  Command: $cmd
  Op:      $op
  Reason:  $reason
  Recovery window: $recovery day(s)

This command is blocked pending confirmation via the destructive-gate-confirmation
skill. Review the operation, consider safer alternatives (e.g. --force-with-lease),
and if you genuinely intend to proceed, invoke the skill explicitly or add
--yes-i-know to the command (protected-destructive ops cannot be bypassed).

Exit code 2 — Claude should surface this to the user and/or invoke the skill.
EOF
exit 2
