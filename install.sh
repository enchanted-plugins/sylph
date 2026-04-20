#!/usr/bin/env bash
# Weaver installer. Clones the monorepo so shared/scripts is available
# for hook invocations. No host-specific tooling is installed here —
# that happens later, interactively, via `/weaver:setup` from inside
# your project, which detects the host from `git remote` and only
# installs what's needed.
set -euo pipefail

REPO="https://github.com/enchanted-plugins/weaver"
WEAVER_DIR="${HOME}/.claude/plugins/weaver"

step() { printf "\n\033[1;36m▸ %s\033[0m\n" "$*"; }
ok()   { printf "  \033[32m✓\033[0m %s\n" "$*"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$*" >&2; }

step "Weaver installer"

# ── 1. Prerequisites ──
if ! command -v git >/dev/null 2>&1; then
    warn "git not found on PATH — Weaver requires git"
    exit 1
fi
ok "git present"

# ── 2. Clone or update the monorepo ──
if [[ -d "$WEAVER_DIR/.git" ]]; then
    git -C "$WEAVER_DIR" pull --ff-only --quiet
    ok "Updated existing clone at $WEAVER_DIR"
else
    git clone --depth 1 --quiet "$REPO" "$WEAVER_DIR"
    ok "Cloned to $WEAVER_DIR"
fi

# ── 3. Verify shared/scripts is usable ──
if [[ ! -f "$WEAVER_DIR/shared/scripts/destructive_patterns.py" ]]; then
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
    warn "Python 3 not found on PATH — hooks will fail. Install Python 3.8+ before running Weaver."
else
    ok "Python 3 present ($PY)"
fi

cat <<'EOF'

─────────────────────────────────────────────────────────────────────────
  Weaver ships as 8 plugins + a `full` meta-plugin that declares them
  all as dependencies. One command installs the whole chain.
─────────────────────────────────────────────────────────────────────────

  STEP 1 — Inside Claude Code, run:

    /plugin marketplace add enchanted-plugins/weaver
    /plugin install full@weaver

  STEP 2 — From inside the project you want to use Weaver on, run:

    /weaver:setup

  That detects the git host from your `origin` remote (GitHub, GitLab,
  Bitbucket, Azure DevOps, Gitea/Forgejo/Codeberg, AWS CodeCommit,
  or SourceHut), then installs / configures only what that host needs.
  Skip it for now — Weaver will run in degraded mode (commit drafting
  + destructive-op gate + W2 clustering all work without a host token)
  and you can run /weaver:setup later.

  VERIFY:   /plugin list       → should show `full` + 8 plugins.
            /weaver:status     → should detect the workflow + CI.

EOF
