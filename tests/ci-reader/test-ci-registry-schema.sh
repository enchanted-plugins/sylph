#!/usr/bin/env bash
# Test: ci-registry.json has all 10 CI systems with required schema fields.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

REGISTRY="$PLUGINS_ROOT/ci-reader/state/ci-registry.json"
assert_file_exists "$REGISTRY"
assert_json_valid "$REGISTRY"

# Top-level shape.
assert_jq "$REGISTRY" '.schema_version' "1.0" "schema_version"
assert_jq "$REGISTRY" '.last_updated | type' "string" "last_updated is a string"
assert_jq "$REGISTRY" '.source_of_truth | type' "string" "source_of_truth is a string"

# Every CI system listed in the architecture document.
expected_systems=(
    "github_actions" "gitlab_ci" "circleci" "jenkins" "buildkite"
    "drone" "woodpecker" "tekton" "argocd" "wixiecd"
)

system_count="$(jq '.systems | length' "$REGISTRY")"
assert_eq "$system_count" "${#expected_systems[@]}" "system count"

# Each system present.
for sys in "${expected_systems[@]}"; do
    present="$(jq --arg s "$sys" '.systems[$s] | if . then "yes" else "no" end' "$REGISTRY")"
    assert_eq "$present" '"yes"' "system $sys present"
done

# Each system has the required schema fields.
required_fields=(
    "id" "display_name" "status_api_path" "log_stream_api" "rerun_api"
    "auth_modes" "rate_limits" "webhook_event_taxonomy"
    "status_enum" "conclusion_enum"
    "supports_check_runs" "supports_required_status" "gate_merge_queue"
    "known_quirks" "support_level"
)

for sys in "${expected_systems[@]}"; do
    for field in "${required_fields[@]}"; do
        # `has` returns true even when the value is null — exactly what we want
        # because status_api_path / log_stream_api / rerun_api are legitimately
        # null for GitOps systems.
        present="$(jq --arg s "$sys" --arg f "$field" '.systems[$s] | has($f)' "$REGISTRY")"
        assert_eq "$present" "true" "system $sys has field $field"
    done
done

# Type shape: array-valued fields must be arrays.
array_fields=(
    "auth_modes" "webhook_event_taxonomy" "status_enum" "conclusion_enum" "known_quirks"
)
for sys in "${expected_systems[@]}"; do
    for field in "${array_fields[@]}"; do
        t="$(jq -r --arg s "$sys" --arg f "$field" '.systems[$s][$f] | type' "$REGISTRY")"
        assert_eq "$t" "array" "system $sys field $field is array"
    done
done

# Type shape: bool fields must be bools.
bool_fields=("supports_check_runs" "supports_required_status" "gate_merge_queue")
for sys in "${expected_systems[@]}"; do
    for field in "${bool_fields[@]}"; do
        t="$(jq -r --arg s "$sys" --arg f "$field" '.systems[$s][$f] | type' "$REGISTRY")"
        assert_eq "$t" "boolean" "system $sys field $field is boolean"
    done
done

# rate_limits is an object with the three documented keys.
for sys in "${expected_systems[@]}"; do
    t="$(jq -r --arg s "$sys" '.systems[$s].rate_limits | type' "$REGISTRY")"
    assert_eq "$t" "object" "system $sys rate_limits is object"
    for sub in "authenticated_per_hour" "app_per_hour" "notes"; do
        present="$(jq --arg s "$sys" --arg f "$sub" '.systems[$s].rate_limits | has($f)' "$REGISTRY")"
        assert_eq "$present" "true" "system $sys rate_limits has $sub"
    done
done

# Support-level values are from the enum.
for sys in "${expected_systems[@]}"; do
    level="$(jq -r --arg s "$sys" '.systems[$s].support_level' "$REGISTRY")"
    case "$level" in
        first-class|best-effort|read-only|out-of-scope) ;;
        *) fail "system $sys has invalid support_level: $level" ;;
    esac
done

# Honesty check: per the internal audit, only github_actions is first-class.
first_class="$(jq -r '[.systems[] | select(.support_level == "first-class") | .id] | sort | join(",")' "$REGISTRY")"
assert_eq "$first_class" "github_actions" "only github_actions is first-class"

# GitOps systems must be read-only (ArgoCD and WixieCD).
for gitops in "argocd" "wixiecd"; do
    level="$(jq -r --arg s "$gitops" '.systems[$s].support_level' "$REGISTRY")"
    assert_eq "$level" "read-only" "$gitops is read-only (GitOps, not gate-ready)"
    gmq="$(jq -r --arg s "$gitops" '.systems[$s].gate_merge_queue' "$REGISTRY")"
    assert_eq "$gmq" "false" "$gitops does not gate merge queue"
done

# Jenkins quirk: the UNSTABLE ≠ success lesson must be encoded.
jenkins_quirks="$(jq -r '.systems.jenkins.known_quirks | join(" ")' "$REGISTRY")"
assert_contains "$jenkins_quirks" "UNSTABLE" "Jenkins UNSTABLE quirk documented"

# GitHub Check Runs preference must be captured.
gha_quirks="$(jq -r '.systems.github_actions.known_quirks | join(" ")' "$REGISTRY")"
assert_contains "$gha_quirks" "Check Runs" "GitHub Actions Check Runs preference documented"

# ID field must match the key (self-consistency).
for sys in "${expected_systems[@]}"; do
    idv="$(jq -r --arg s "$sys" '.systems[$s].id' "$REGISTRY")"
    assert_eq "$idv" "$sys" "system $sys .id matches key"
done

ok "10 CI systems with all ${#required_fields[@]} required schema fields; support levels valid; audit honesty preserved"
