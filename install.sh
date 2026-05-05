#!/usr/bin/env bash
# Sylph installer. Clones the monorepo so shared/scripts is available
# for hook invocations. No host-specific tooling is installed here —
# that happens later, interactively, via `/sylph:setup` from inside
# your project, which detects the host from `git remote` and only
# installs what's needed.
set -euo pipefail

REPO="https://github.com/enchanter-ai/sylph"
SYLPH_DIR="${HOME}/.claude/plugins/sylph"

step() { printf "\n\033[1;36m▸ %s\033[0m\n" "$*"; }
ok()   { printf "  \033[32m✓\033[0m %s\n" "$*"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$*" >&2; }

step "Sylph installer"

# ── 1. Prerequisites ──
if ! command -v git >/dev/null 2>&1; then
    warn "git not found on PATH — Sylph requires git"
    exit 1
fi
ok "git present"

# ── 2. Clone or update the monorepo ──
if [[ -d "$SYLPH_DIR/.git" ]]; then
    git -C "$SYLPH_DIR" pull --ff-only --quiet
    ok "Updated existing clone at $SYLPH_DIR"
else
    git clone --depth 1 --quiet "$REPO" "$SYLPH_DIR"
    ok "Cloned to $SYLPH_DIR"
fi

# ── 3. Verify shared/scripts is usable ──
if [[ ! -f "$SYLPH_DIR/shared/scripts/destructive_patterns.py" ]]; then
    warn "shared/scripts/ missing — clone may have failed"
    exit 1
fi

PY=""
if command -v python3 >/dev/null 2>&1 && python3 -c "import sys; print(sys.version_info[0])" 2>/dev/null | grep -qE '^3$'; then
    PY="python3"
elif command -v python >/dev/null 2>&1 && python -c "import sys; print(sys.version_info[0])" 2>/dev/null | grep -qE '^3$'; then
    PY="python"
fi
if [[ -z "$PY" ]]; then
    warn "Python 3 not found on PATH — hooks will fail. Install Python 3.8+ before running Sylph."
else
    ok "Python 3 present ($PY)"
fi

cat <<'EOF'

─────────────────────────────────────────────────────────────────────────
  Sylph ships as 8 plugins + a `full` meta-plugin that declares them
  all as dependencies. One command installs the whole chain.
─────────────────────────────────────────────────────────────────────────

  STEP 1 — Inside Claude Code, run:

    /plugin marketplace add enchanter-ai/sylph
    /plugin install full@sylph

  STEP 2 — From inside the project you want to use Sylph on, run:

    /sylph:setup

  That detects the git host from your `origin` remote (GitHub, GitLab,
  Bitbucket, Azure DevOps, Gitea/Forgejo/Codeberg, AWS CodeCommit,
  or SourceHut), then installs / configures only what that host needs.
  Skip it for now — Sylph will run in degraded mode (commit drafting
  + destructive-op gate + W2 clustering all work without a host token)
  and you can run /sylph:setup later.

  VERIFY:   /plugin list       → should show `full` + 8 plugins.
            /sylph:status     → should detect the workflow + CI.

EOF
