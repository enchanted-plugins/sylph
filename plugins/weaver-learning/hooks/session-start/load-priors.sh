#!/usr/bin/env bash
# weaver-learning SessionStart — load W5 priors into a session cache so W1/W2/W3/W4
# can consult them without re-reading the full learnings.json on every event.
#
# Emits a one-line status to stderr:
#   "[weaver-learning] priors loaded (N samples, confident=true|false)"
#
# Dependencies: bash, python3. jq optional.

set -euo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$(dirname "$(dirname "$0")")")}"
PRODUCT_ROOT="$(dirname "$(dirname "$PLUGIN_ROOT")")"
STATE_FILE="$PLUGIN_ROOT/state/learnings.json"
PRIORS_CACHE="$PLUGIN_ROOT/state/priors.json"

mkdir -p "$(dirname "$STATE_FILE")"

# Resolve Python (handles Windows Store stub).
PY=""
if command -v python3 >/dev/null 2>&1 && python3 -c "import sys; print(sys.version_info[0])" 2>/dev/null | grep -qE '^3$'; then
    PY="python3"
elif command -v python >/dev/null 2>&1 && python -c "import sys; print(sys.version_info[0])" 2>/dev/null | grep -qE '^3$'; then
    PY="python"
fi
[[ -z "$PY" ]] && exit 0  # no Python — skip gracefully

# Compute priors → session cache
"$PY" "$PRODUCT_ROOT/shared/scripts/gauss_learning.py" priors "$STATE_FILE" > "$PRIORS_CACHE" 2>/dev/null || exit 0

# Status line
if command -v jq >/dev/null 2>&1; then
    samples="$(jq -r '.sample_count // 0' "$PRIORS_CACHE")"
    confident="$(jq -r '.confident // false' "$PRIORS_CACHE")"
    printf '[weaver-learning] priors loaded (%s samples, confident=%s)\n' "$samples" "$confident" >&2
fi

exit 0
