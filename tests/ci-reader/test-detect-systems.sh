#!/usr/bin/env bash
# Test: ci_adapters.detect_system recognizes each CI config file / directory.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

detect() {
    local target
    target="$(py_path "$1")"
    "$PY" -c "
import sys; sys.path.insert(0, r'$SHARED_SCRIPTS_PY')
from ci_adapters import detect_system
from pathlib import Path
print(','.join(detect_system(Path(r'$target'))))
"
}

# Empty dir → no systems.
dir="$(mktemp -d)"
assert_eq "$(detect "$dir")" "" "empty repo: no CI detected"
rm -rf "$dir"
ok "empty repo: no CI systems"

# GitHub Actions
dir="$(mktemp -d)"
mkdir -p "$dir/.github/workflows"
touch "$dir/.github/workflows/test.yml"
assert_contains "$(detect "$dir")" "github-actions" "github-actions detected"
rm -rf "$dir"
ok ".github/workflows/ → github-actions"

# GitLab CI
dir="$(mktemp -d)"
touch "$dir/.gitlab-ci.yml"
assert_contains "$(detect "$dir")" "gitlab-ci" "gitlab-ci detected"
rm -rf "$dir"
ok ".gitlab-ci.yml → gitlab-ci"

# CircleCI
dir="$(mktemp -d)"
mkdir -p "$dir/.circleci"
touch "$dir/.circleci/config.yml"
assert_contains "$(detect "$dir")" "circleci" "circleci detected"
rm -rf "$dir"
ok ".circleci/config.yml → circleci"

# Jenkins
dir="$(mktemp -d)"
touch "$dir/Jenkinsfile"
assert_contains "$(detect "$dir")" "jenkins" "jenkins detected"
rm -rf "$dir"
ok "Jenkinsfile → jenkins"

# Buildkite
dir="$(mktemp -d)"
mkdir "$dir/.buildkite"
assert_contains "$(detect "$dir")" "buildkite" "buildkite detected"
rm -rf "$dir"
ok ".buildkite/ → buildkite"

# Drone
dir="$(mktemp -d)"
touch "$dir/.drone.yml"
assert_contains "$(detect "$dir")" "drone" "drone detected"
rm -rf "$dir"
ok ".drone.yml → drone"

# Woodpecker
dir="$(mktemp -d)"
touch "$dir/.woodpecker.yml"
assert_contains "$(detect "$dir")" "woodpecker" "woodpecker detected"
rm -rf "$dir"
ok ".woodpecker.yml → woodpecker"

# Mixed repo (multiple systems)
dir="$(mktemp -d)"
mkdir -p "$dir/.github/workflows" "$dir/.circleci"
touch "$dir/.github/workflows/test.yml" "$dir/.circleci/config.yml" "$dir/.drone.yml"
result="$(detect "$dir")"
assert_contains "$result" "github-actions" "multi-CI: github-actions"
assert_contains "$result" "circleci" "multi-CI: circleci"
assert_contains "$result" "drone" "multi-CI: drone"
rm -rf "$dir"
ok "mixed repo: all 3 systems detected simultaneously"
