#!/usr/bin/env bash
# Test: capability-registry.json has all 10 hosts with required schema fields.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

REGISTRY="$PLUGINS_ROOT/capability-memory/state/capability-registry.json"
assert_file_exists "$REGISTRY"
assert_json_valid "$REGISTRY"

# Schema version must be current.
schema_version="$(jq -r '.schema_version' "$REGISTRY")"
assert_eq "$schema_version" "1.1" "schema_version"

# schema_changelog must be present and non-empty.
changelog_len="$(jq '.schema_changelog | length' "$REGISTRY")"
if [[ "$changelog_len" -lt 1 ]]; then
    fail "schema_changelog must have at least one entry (got $changelog_len)"
fi

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
# v1.0 fields (13) + v1.1 fields (10) = 23 required fields.
# Fields whose value may legitimately be `false` or null use `has()` rather
# than a truthiness check.
truthy_fields=(
    "id" "display_name" "api_base" "auth_modes" "rate_limits"
    "webhook_signing" "merge_strategies" "codeowners_flavor"
    "known_quirks" "support_level"
    "signed_commit_verification" "protected_branch_api"
    "default_branch_convention" "lfs_variant" "webhook_event_taxonomy"
    "pat_scopes_required" "commit_status_api_shape"
)

presence_fields=(
    "has_merge_queue" "has_draft_pr" "release_asset_support"
    "release_api_path" "signed_tag_support" "supports_draft_protected_branch_override"
)

for host in "${expected_hosts[@]}"; do
    for field in "${truthy_fields[@]}"; do
        present="$(jq --arg h "$host" --arg f "$field" '.hosts[$h][$f] | if . != null then "yes" else "no" end' "$REGISTRY")"
        assert_eq "$present" '"yes"' "host $host has truthy field $field"
    done
    for field in "${presence_fields[@]}"; do
        present="$(jq --arg h "$host" --arg f "$field" '.hosts[$h] | has($f) | if . then "yes" else "no" end' "$REGISTRY")"
        assert_eq "$present" '"yes"' "host $host has field key $field"
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

ok "10 hosts with all 23 required schema fields (v1.1); support levels valid"
