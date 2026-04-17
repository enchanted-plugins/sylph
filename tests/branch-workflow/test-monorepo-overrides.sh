#!/usr/bin/env bash
# Test: .weaver/workflow-map.yaml overlays surface in detect() output.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

dir="$(mktemp -d)"
git -C "$dir" init -q -b main
git -C "$dir" config user.email t@w.l
git -C "$dir" config user.name t
echo x > "$dir/README.md"
git -C "$dir" add . && git -C "$dir" commit -q -m "chore: seed"
mkdir -p "$dir/.weaver"

cat > "$dir/.weaver/workflow-map.yaml" <<'EOF'
# monorepo overlay
packages/mobile: release-flow
packages/web: trunk-based
services/api: github-flow
# invalid label — should be dropped silently
services/legacy: not-a-workflow
EOF

result="$("$PY" "$SHARED_SCRIPTS/workflow_detect.py" detect "$dir")"
mobile="$(printf '%s' "$result" | jq -r '.subtree_overrides."packages/mobile"')"
web="$(printf '%s' "$result" | jq -r '.subtree_overrides."packages/web"')"
api="$(printf '%s' "$result" | jq -r '.subtree_overrides."services/api"')"
legacy="$(printf '%s' "$result" | jq -r '.subtree_overrides."services/legacy"')"

assert_eq "$mobile" "release-flow" "mobile override"
assert_eq "$web" "trunk-based" "web override"
assert_eq "$api" "github-flow" "api override"
assert_eq "$legacy" "null" "invalid label dropped (not in LABELS set)"

ok "workflow-map.yaml: 3 valid overrides surface, 1 invalid label dropped"

rm -rf "$dir"
