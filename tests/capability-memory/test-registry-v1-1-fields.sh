#!/usr/bin/env bash
# Test: capability-registry.json v1.1 new-field shape checks.
#
# Shape-validates the 10 fields introduced in schema_version 1.1 for every host:
#   signed_commit_verification (object)
#   protected_branch_api (object)
#   default_branch_convention (enum string | null)
#   lfs_variant (enum string)
#   release_api_path (string | null)
#   webhook_event_taxonomy (object)
#   pat_scopes_required (array<string>)
#   signed_tag_support (bool)
#   commit_status_api_shape (enum string)
#   supports_draft_protected_branch_override (bool)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

REGISTRY="$PLUGINS_ROOT/capability-memory/state/capability-registry.json"
assert_file_exists "$REGISTRY"
assert_json_valid "$REGISTRY"

HOSTS=(
    "github" "gitlab" "bitbucket-cloud" "bitbucket-dc"
    "azure-devops" "gitea" "forgejo" "codeberg"
    "codecommit" "sourcehut"
)

# Permitted enum values.
SIGNING_MECHS_RE='^(gpg|ssh|sigstore)$'
BRANCH_CONVENTIONS='main master trunk develop'
LFS_VARIANTS='git-lfs git-annex none'
CI_SHAPES='check-runs statuses pipelines both none'

in_list() {
    # in_list <value> <space-separated-allowed>
    local needle="$1"
    shift
    for v in $*; do
        if [[ "$needle" == "$v" ]]; then return 0; fi
    done
    return 1
}

jq_type() {
    # jq_type <file> <path>  →  echoes jq type string
    jq -r "$2 | type" "$1"
}

for host in "${HOSTS[@]}"; do
    # ── signed_commit_verification: object with supported(bool), mechanisms(array), api_field(string|null) ──
    t="$(jq_type "$REGISTRY" ".hosts[\"$host\"].signed_commit_verification")"
    assert_eq "$t" "object" "$host.signed_commit_verification type"

    t="$(jq_type "$REGISTRY" ".hosts[\"$host\"].signed_commit_verification.supported")"
    assert_eq "$t" "boolean" "$host.signed_commit_verification.supported type"

    t="$(jq_type "$REGISTRY" ".hosts[\"$host\"].signed_commit_verification.mechanisms")"
    assert_eq "$t" "array" "$host.signed_commit_verification.mechanisms type"

    # Every mechanism must be from the enum.
    bad_mechs="$(jq -r --arg h "$host" '.hosts[$h].signed_commit_verification.mechanisms[]' "$REGISTRY" | grep -Ev "$SIGNING_MECHS_RE" || true)"
    if [[ -n "$bad_mechs" ]]; then
        fail "$host.signed_commit_verification.mechanisms has invalid entry: $bad_mechs"
    fi

    # If supported=true, mechanisms must be non-empty.
    supported="$(jq -r --arg h "$host" '.hosts[$h].signed_commit_verification.supported' "$REGISTRY")"
    mech_count="$(jq -r --arg h "$host" '.hosts[$h].signed_commit_verification.mechanisms | length' "$REGISTRY")"
    if [[ "$supported" == "true" && "$mech_count" -lt 1 ]]; then
        fail "$host.signed_commit_verification supported=true but mechanisms is empty"
    fi

    # api_field must be string or null.
    t="$(jq_type "$REGISTRY" ".hosts[\"$host\"].signed_commit_verification.api_field")"
    case "$t" in
        string|null) ;;
        *) fail "$host.signed_commit_verification.api_field must be string|null, got $t" ;;
    esac

    # ── protected_branch_api: object with supported(bool), endpoint(string|null), requires_admin(bool) ──
    t="$(jq_type "$REGISTRY" ".hosts[\"$host\"].protected_branch_api")"
    assert_eq "$t" "object" "$host.protected_branch_api type"

    t="$(jq_type "$REGISTRY" ".hosts[\"$host\"].protected_branch_api.supported")"
    assert_eq "$t" "boolean" "$host.protected_branch_api.supported type"

    t="$(jq_type "$REGISTRY" ".hosts[\"$host\"].protected_branch_api.endpoint")"
    case "$t" in
        string|null) ;;
        *) fail "$host.protected_branch_api.endpoint must be string|null, got $t" ;;
    esac

    t="$(jq_type "$REGISTRY" ".hosts[\"$host\"].protected_branch_api.requires_admin")"
    assert_eq "$t" "boolean" "$host.protected_branch_api.requires_admin type"

    # ── default_branch_convention: enum string | null ──
    t="$(jq_type "$REGISTRY" ".hosts[\"$host\"].default_branch_convention")"
    case "$t" in
        string|null) ;;
        *) fail "$host.default_branch_convention must be string|null, got $t" ;;
    esac

    if [[ "$t" == "string" ]]; then
        val="$(jq -r --arg h "$host" '.hosts[$h].default_branch_convention' "$REGISTRY")"
        if ! in_list "$val" "$BRANCH_CONVENTIONS"; then
            fail "$host.default_branch_convention invalid value: $val (expected one of: $BRANCH_CONVENTIONS)"
        fi
    fi

    # ── lfs_variant: enum string ──
    t="$(jq_type "$REGISTRY" ".hosts[\"$host\"].lfs_variant")"
    assert_eq "$t" "string" "$host.lfs_variant type"

    val="$(jq -r --arg h "$host" '.hosts[$h].lfs_variant' "$REGISTRY")"
    if ! in_list "$val" "$LFS_VARIANTS"; then
        fail "$host.lfs_variant invalid value: $val (expected one of: $LFS_VARIANTS)"
    fi

    # ── release_api_path: string | null ──
    t="$(jq_type "$REGISTRY" ".hosts[\"$host\"].release_api_path")"
    case "$t" in
        string|null) ;;
        *) fail "$host.release_api_path must be string|null, got $t" ;;
    esac

    # ── webhook_event_taxonomy: object with pr_event(non-empty string), push_event(non-empty string), ci_event(string|null) ──
    t="$(jq_type "$REGISTRY" ".hosts[\"$host\"].webhook_event_taxonomy")"
    assert_eq "$t" "object" "$host.webhook_event_taxonomy type"

    pr_ev="$(jq -r --arg h "$host" '.hosts[$h].webhook_event_taxonomy.pr_event' "$REGISTRY")"
    if [[ -z "$pr_ev" || "$pr_ev" == "null" ]]; then
        fail "$host.webhook_event_taxonomy.pr_event must be non-empty string (got: '$pr_ev')"
    fi

    push_ev="$(jq -r --arg h "$host" '.hosts[$h].webhook_event_taxonomy.push_event' "$REGISTRY")"
    if [[ -z "$push_ev" || "$push_ev" == "null" ]]; then
        fail "$host.webhook_event_taxonomy.push_event must be non-empty string (got: '$push_ev')"
    fi

    t="$(jq_type "$REGISTRY" ".hosts[\"$host\"].webhook_event_taxonomy.ci_event")"
    case "$t" in
        string|null) ;;
        *) fail "$host.webhook_event_taxonomy.ci_event must be string|null, got $t" ;;
    esac

    # ── pat_scopes_required: array of strings ──
    t="$(jq_type "$REGISTRY" ".hosts[\"$host\"].pat_scopes_required")"
    assert_eq "$t" "array" "$host.pat_scopes_required type"

    non_string="$(jq -r --arg h "$host" '.hosts[$h].pat_scopes_required[] | select(type != "string")' "$REGISTRY" || true)"
    if [[ -n "$non_string" ]]; then
        fail "$host.pat_scopes_required contains non-string element(s)"
    fi

    # ── signed_tag_support: bool ──
    t="$(jq_type "$REGISTRY" ".hosts[\"$host\"].signed_tag_support")"
    assert_eq "$t" "boolean" "$host.signed_tag_support type"

    # ── commit_status_api_shape: enum string ──
    t="$(jq_type "$REGISTRY" ".hosts[\"$host\"].commit_status_api_shape")"
    assert_eq "$t" "string" "$host.commit_status_api_shape type"

    val="$(jq -r --arg h "$host" '.hosts[$h].commit_status_api_shape' "$REGISTRY")"
    if ! in_list "$val" "$CI_SHAPES"; then
        fail "$host.commit_status_api_shape invalid value: $val (expected one of: $CI_SHAPES)"
    fi

    # ── supports_draft_protected_branch_override: bool ──
    t="$(jq_type "$REGISTRY" ".hosts[\"$host\"].supports_draft_protected_branch_override")"
    assert_eq "$t" "boolean" "$host.supports_draft_protected_branch_override type"
done

# ── Cross-host consistency sanity checks ──

# Bitbucket Cloud: webhooks UNSIGNED and no signed-commit-verification (documented quirk).
assert_jq "$REGISTRY" '.hosts["bitbucket-cloud"].webhook_signing' "none" \
    "bitbucket-cloud webhook_signing must be 'none'"
assert_jq "$REGISTRY" '.hosts["bitbucket-cloud"].signed_commit_verification.supported' "false" \
    "bitbucket-cloud signed_commit_verification.supported must be false"

# SourceHut: patch-email workflow → pr_event must be 'email'; no release API.
assert_jq "$REGISTRY" '.hosts["sourcehut"].webhook_event_taxonomy.pr_event' "email" \
    "sourcehut pr_event must be 'email'"
assert_jq "$REGISTRY" '.hosts["sourcehut"].release_api_path' "null" \
    "sourcehut release_api_path must be null"

# CodeCommit: no webhooks via repo-level subscription → ci_event null; no release API.
assert_jq "$REGISTRY" '.hosts["codecommit"].webhook_event_taxonomy.ci_event' "null" \
    "codecommit ci_event must be null"
assert_jq "$REGISTRY" '.hosts["codecommit"].release_api_path' "null" \
    "codecommit release_api_path must be null"
assert_jq "$REGISTRY" '.hosts["codecommit"].commit_status_api_shape' "none" \
    "codecommit commit_status_api_shape must be 'none'"

# GitHub: first-class Check Runs.
assert_jq "$REGISTRY" '.hosts["github"].commit_status_api_shape' "check-runs" \
    "github commit_status_api_shape must be 'check-runs'"

# GitLab: pipelines for CI status.
assert_jq "$REGISTRY" '.hosts["gitlab"].commit_status_api_shape' "pipelines" \
    "gitlab commit_status_api_shape must be 'pipelines'"
assert_jq "$REGISTRY" '.hosts["gitlab"].webhook_event_taxonomy.pr_event' "merge_request" \
    "gitlab pr_event must be 'merge_request'"

ok "v1.1 field shapes validated across 10 hosts (10 new fields each)"
