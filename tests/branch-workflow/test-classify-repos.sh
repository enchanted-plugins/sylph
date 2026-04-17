#!/usr/bin/env bash
# Test: workflow_detect.detect() classifies synthesized mini-repos into the
# expected labels.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

classify() {
    local dir="$1"
    "$PY" "$SHARED_SCRIPTS/workflow_detect.py" detect "$dir" | jq -r '.workflow.label'
}

# Case 1: stacked-diffs (Graphite marker)
dir1="$(mktemp -d)"
git -C "$dir1" init -q -b main
git -C "$dir1" config user.email t@w.l
git -C "$dir1" config user.name t
echo x > "$dir1/README.md"
git -C "$dir1" add . && git -C "$dir1" commit -q -m "chore: seed"
touch "$dir1/.graphite_config"
label="$(classify "$dir1")"
assert_eq "$label" "stacked-diffs" "Graphite marker → stacked-diffs"
rm -rf "$dir1"
ok ".graphite_config → stacked-diffs"

# Case 2: GitFlow (develop + release branch)
dir2="$(mktemp -d)"
git -C "$dir2" init -q -b main
git -C "$dir2" config user.email t@w.l
git -C "$dir2" config user.name t
echo x > "$dir2/README.md"
git -C "$dir2" add . && git -C "$dir2" commit -q -m "chore: seed"
git -C "$dir2" checkout -q -b develop
git -C "$dir2" checkout -q -b release/1.0
label="$(classify "$dir2")"
assert_eq "$label" "gitflow" "develop + release/* → gitflow"
rm -rf "$dir2"
ok "develop + release/* → gitflow"

# Case 3: Trunk-based (single fresh branch)
dir3="$(mktemp -d)"
git -C "$dir3" init -q -b main
git -C "$dir3" config user.email t@w.l
git -C "$dir3" config user.name t
echo x > "$dir3/README.md"
git -C "$dir3" add . && git -C "$dir3" commit -q -m "chore: seed"
label="$(classify "$dir3")"
assert_eq "$label" "trunk-based" "fresh single branch → trunk-based"
rm -rf "$dir3"
ok "single fresh branch → trunk-based"

# Case 4: Explicit .gitflow-config overrides age heuristic
dir4="$(mktemp -d)"
git -C "$dir4" init -q -b main
git -C "$dir4" config user.email t@w.l
git -C "$dir4" config user.name t
echo x > "$dir4/README.md"
git -C "$dir4" add . && git -C "$dir4" commit -q -m "chore: seed"
touch "$dir4/.gitflow-config"
label="$(classify "$dir4")"
assert_eq "$label" "gitflow" ".gitflow-config → gitflow (explicit)"
rm -rf "$dir4"
ok ".gitflow-config → gitflow"
