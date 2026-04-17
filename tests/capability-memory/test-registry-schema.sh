#!/usr/bin/env bash
# Test: capability-registry.json has all 10 hosts with required schema fields.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

REGISTRY="$PLUGINS_ROOT/capability-memory/state/capability-registry.json"
assert_file_exists "$REGISTRY"
assert_json_valid "$REGISTRY"

# Every host listed in the architecture document.
expected_hosts=(
    "github" "gitlab" "bitbucket-cloud" "bitbucket-dc"
    "azure-devops" "gitea" "forgejo" "codeberg"
    "codecommit" "sourcehut"
)

host_count="$(jq '.hosts | length' "$REGISTRY")"
assert_eq "$host_count" "${#expected_hosts[@]}" "host count"

# Each host present.
for host in "${expected_hosts[@]}"; do
    present="$(jq --arg h "$host" '.hosts[$h] | if . then "yes" else "no" end' "$REGISTRY")"
    assert_eq "$present" '"yes"' "host $host present"
done

# Each host has the required schema fields.
required_fields=(
    "id" "display_name" "api_base" "auth_modes" "rate_limits"
    "webhook_signing" "merge_strategies" "has_merge_queue" "has_draft_pr"
    "codeowners_flavor" "release_asset_support" "known_quirks" "support_level"
)

for host in "${expected_hosts[@]}"; do
    for field in "${required_fields[@]}"; do
        present="$(jq --arg h "$host" --arg f "$field" '.hosts[$h][$f] | if . != null then "yes" else "no" end' "$REGISTRY")"
        assert_eq "$present" '"yes"' "host $host has field $field"
    done
done

# Support-level values are from the enum.
for host in "${expected_hosts[@]}"; do
    level="$(jq -r --arg h "$host" '.hosts[$h].support_level' "$REGISTRY")"
    case "$level" in
        first-class|best-effort|read-only|out-of-scope) ;;
        *) fail "host $host has invalid support_level: $level" ;;
    esac
done

ok "10 hosts with all 13 required schema fields; support levels valid"
