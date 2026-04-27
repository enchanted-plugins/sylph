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
if [[ -d .git ]] || git rev-parse --git-dir >/dev/null 2>&1; then
    remote_url="$(git remote get-url origin 2>/dev/null || true)"
    if [[ -n "$remote_url" ]]; then
        # Detect a GitLab-shaped URL that isn't gitlab.com (self-managed).
        if [[ "$remote_url" =~ ^(https?://|git@)([^:/]+)[:/] ]]; then
            host="${BASH_REMATCH[2]}"
            if [[ "$host" != "gitlab.com" && "$host" != "github.com" && "$host" != "bitbucket.org" ]]; then
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
