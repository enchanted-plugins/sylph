---
name: sylph:ci-status
description: Show CI check status for the current branch (or an explicit ref) across every CI system configured in the repo. Detects GitHub Actions, GitLab CI, CircleCI, Jenkins, Buildkite, Drone, Woodpecker, Tekton, ArgoCD, WixieCD. Read-only — Sylph never triggers builds.
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/ci_reader.py *), Bash(python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/ci_reader.py *), Bash(git branch --show-current), Bash(git remote get-url *), Bash(git rev-parse HEAD)
---

# /sylph:ci-status

Aggregate CI status across every system configured in the repo.

## Usage

```
/sylph:ci-status                    # HEAD on the current branch
/sylph:ci-status <sha>              # specific commit
/sylph:ci-status --ref origin/main  # explicit ref
/sylph:ci-status --detect-only      # just show which CI systems are configured
```

## What it does

1. Detects CI systems from repo layout (`ci_adapters.detect_system`).
2. For each system with an available adapter (currently: GitHub Actions
   via `gh`), queries the check-run status for the ref.
3. Normalizes into a typed `Check` list (system, name, status, conclusion,
   url).
4. Emits a gate verdict: `green` / `pending` / `failing` / `no-ci-detected`.
5. For systems without an adapter (GitLab CI, Jenkins, etc.), reports
   `manual_handoff_systems` — the developer checks those externally and
   either forces the merge via the host or waits for a Sylph adapter.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Status fetched (any verdict) |
| 1 | Not in a git repo / no origin |
| 2 | No CI configured |
| 3 | All detected CI systems unavailable (no adapter credentials) |
