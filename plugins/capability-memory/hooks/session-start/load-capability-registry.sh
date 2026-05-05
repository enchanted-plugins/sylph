#!/usr/bin/env bash
# capability-memory SessionStart — warm up the provider capability registry.
#
# 1. Verify the baseline registry file exists and is valid JSON.
# 2. If the current working directory is a git repo, detect the remote host
#    and, for GitLab self-managed, probe /api/v4/version to capture version
#    drift. Cache result for 24h in state/session-cache/.
# 3. Never blocks — session start must not fail on a missing capability.
#
# Dependencies: bash, jq, python3. Zero pip installs.


# Subagent recursion guard — see shared/conduct/hooks.md
if [[ -n "${CLAUDE_SUBAGENT:-}" ]]; then exit 0; fi

set -euo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$(dirname "$(dirname "$0")")")}"
PRODUCT_ROOT="$(dirname "$(dirname "$PLUGIN_ROOT")")"
REGISTRY="$PLUGIN_ROOT/state/capability-registry.json"
SESSION_CACHE_DIR="$PLUGIN_ROOT/state/session-cache"

mkdir -p "$SESSION_CACHE_DIR"

# 1. Registry must exist and be valid JSON.
if [[ ! -f "$REGISTRY" ]]; then
    echo "[capability-memory] Registry missing at $REGISTRY — run install.sh" >&2
    exit 0
fi

if ! jq empty "$REGISTRY" >/dev/null 2>&1; then
    echo "[capability-memory] Registry at $REGISTRY is invalid JSON — skipping" >&2
    exit 0
fi

# 2. GitLab self-managed probe (only if current dir is a git repo with a GitLab remote).
#
# Probe allowlist: only hosts the developer has pre-authorized are probed at all.
# A malicious repo can plant `git remote set-url origin https://attacker.example/...`;
# without an allowlist this hook would emit an HTTPS request to attacker-controlled
# infrastructure on every session start, leaking session presence + timing.
# Default allow: github.com, gitlab.com, bitbucket.org, codeberg.org. For any
# other host the probe is skipped and an advisory is emitted. To enable probing
# for a self-managed instance, append the host to SYLPH_PROBE_ALLOWLIST (space-
# or comma-separated) in your shell env or .claude/settings.json env block.
PROBE_ALLOWLIST_DEFAULT="github.com gitlab.com bitbucket.org codeberg.org"
PROBE_ALLOWLIST_USER="${SYLPH_PROBE_ALLOWLIST:-}"
# Normalize commas to spaces for either form.
PROBE_ALLOWLIST_USER="${PROBE_ALLOWLIST_USER//,/ }"
PROBE_ALLOWLIST="$PROBE_ALLOWLIST_DEFAULT $PROBE_ALLOWLIST_USER"

host_in_allowlist() {
    local needle="$1"
    local entry
    for entry in $PROBE_ALLOWLIST; do
        [[ "$entry" == "$needle" ]] && return 0
    done
    return 1
}

if [[ -d .git ]] || git rev-parse --git-dir >/dev/null 2>&1; then
    remote_url="$(git remote get-url origin 2>/dev/null || true)"
    if [[ -n "$remote_url" ]]; then
        # Detect a GitLab-shaped URL that isn't gitlab.com (self-managed).
        if [[ "$remote_url" =~ ^(https?://|git@)([^:/]+)[:/] ]]; then
            host="${BASH_REMATCH[2]}"
            # Skip well-known hosts that don't need GitLab self-managed probing.
            if [[ "$host" == "github.com" || "$host" == "gitlab.com" || "$host" == "bitbucket.org" ]]; then
                : # noop — first-class hosts; capability covered by static registry.
            elif ! host_in_allowlist "$host"; then
                # Unknown host — refuse to probe; emit advisory.
                {
                    echo "=== capability-memory (advisory) ==="
                    echo "Skipping registry probe for unknown host $host. Add to allowlist if intended."
                    echo "Hint: export SYLPH_PROBE_ALLOWLIST=\"$host\" (space- or comma-separated for multiple)."
                } >&2
            else
                # Could be GitLab self-managed, Gitea, Forgejo, etc. Try GitLab first.
                cache_file="$SESSION_CACHE_DIR/gitlab-version-${host//[^a-zA-Z0-9]/_}.json"

                # Use cached probe result if <24h old.
                cache_fresh=false
                if [[ -f "$cache_file" ]]; then
                    cache_age_secs=$(( $(date +%s) - $(stat -c %Y "$cache_file" 2>/dev/null || stat -f %m "$cache_file" 2>/dev/null || echo 0) ))
                    if (( cache_age_secs < 86400 )); then
                        cache_fresh=true
                    fi
                fi

                if ! $cache_fresh; then
                    # Probe /api/v4/version (GitLab) — non-blocking, 3s timeout.
                    scheme="https"
                    [[ "$remote_url" =~ ^http:// ]] && scheme="http"
                    version_url="${scheme}://${host}/api/v4/version"

                    if command -v curl >/dev/null 2>&1; then
                        probe="$(curl -sS --max-time 3 "$version_url" 2>/dev/null || true)"
                        if [[ -n "$probe" ]] && printf '%s' "$probe" | jq empty >/dev/null 2>&1; then
                            printf '{"host":"%s","probed_at":"%s","version_response":%s}\n' \
                                "$host" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$probe" > "$cache_file"
                        fi
                    fi
                fi
            fi
        fi
    fi
fi

# 3. Never fail session start. Surface a one-line status.
host_count="$(jq '.hosts | length' "$REGISTRY" 2>/dev/null || echo '?')"
printf '[capability-memory] Loaded registry: %s hosts\n' "$host_count" >&2
exit 0
