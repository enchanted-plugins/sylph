#!/usr/bin/env bash
# ci-reader SessionStart — warm up the CI capability registry.
#
# 1. Verify the baseline registry file exists and is valid JSON.
# 2. Summarise system count + support-level breakdown on stderr.
# 3. Never blocks — session start must not fail on a missing registry.
#
# Dependencies: bash, jq. Zero pip installs.


# Subagent recursion guard — see shared/conduct/hooks.md
if [[ -n "${CLAUDE_SUBAGENT:-}" ]]; then exit 0; fi

set -euo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$(dirname "$(dirname "$0")")")}"
REGISTRY="$PLUGIN_ROOT/state/ci-registry.json"

# 1. Registry must exist and be valid JSON.
if [[ ! -f "$REGISTRY" ]]; then
    echo "[ci-reader] Registry missing at $REGISTRY — run install.sh" >&2
    exit 0
fi

if ! jq empty "$REGISTRY" >/dev/null 2>&1; then
    echo "[ci-reader] Registry at $REGISTRY is invalid JSON — skipping" >&2
    exit 0
fi

# 2. Never fail session start. Surface a one-line status.
system_count="$(jq '.systems | length' "$REGISTRY" 2>/dev/null || echo '?')"
first_class_count="$(jq '[.systems[] | select(.support_level == "first-class")] | length' "$REGISTRY" 2>/dev/null || echo '?')"
printf '[ci-reader] ci-registry: %s systems loaded, %s first-class\n' "$system_count" "$first_class_count" >&2
exit 0
