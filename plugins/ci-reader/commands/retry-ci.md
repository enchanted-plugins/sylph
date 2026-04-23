---
name: sylph:retry-ci
description: Rerun failing CI checks on the current ref. Only re-runs EXISTING runs — never triggers a fresh build from scratch.
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/ci_reader.py *), Bash(python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/ci_reader.py *), Bash(gh run rerun *), Bash(git remote get-url *), Bash(git rev-parse HEAD)
---

# /sylph:retry-ci

Rerun failing CI checks on the current branch's HEAD commit.

## Usage

```
/sylph:retry-ci                   # rerun all failing checks on HEAD
/sylph:retry-ci --name "tests"    # only rerun checks matching a name substring
/sylph:retry-ci --all             # rerun ALL checks, not just failures (incl. skipped/cancelled)
/sylph:retry-ci --ref <sha>       # explicit ref instead of HEAD
```

## What "retry" means

- **Sylph re-runs existing builds** — e.g., `gh run rerun <run-id>`,
  GitLab's `/jobs/:id/retry`, CircleCI's `/workflow/:id/rerun`.
- **Sylph does NOT trigger NEW builds.** New builds from scratch are
  out of scope — Sylph is a git-workflow plugin, and CI execution
  belongs to your existing CI pipelines (push-triggered workflows, etc.).
  When no existing run can be re-run, Sylph reports and stops.

## Flow

```
1. Read CI status via ci-reader.
2. Filter to failing (or all with --all) checks.
3. For each: call adapter.rerun(check_id). Adapters that don't
   support retry (Tekton — re-apply the CRD; ArgoCD/WixieCD — GitOps)
   emit sylph.ci.trigger.requested instead.
4. Poll status once after 5s; print the new state.
```

## Per-adapter behavior

| System | Retry mechanism |
|---|---|
| GitHub Actions | `gh run rerun --failed` or REST `/actions/runs/{id}/rerun-failed-jobs` |
| GitLab CI | `POST /projects/:id/jobs/:id/retry` |
| CircleCI | `POST /workflow/{id}/rerun` |
| Jenkins | `POST /job/{name}/{build}/rebuild` — requires CSRF crumb (adapter handles) |
| Buildkite | `PUT /builds/{id}/retry` |
| Drone / Woodpecker | `POST /api/repos/{repo}/builds/{n}` (new-build trigger) |
| Tekton | `kubectl delete pipelinerun/X && kubectl apply ...` — manual for now |
| ArgoCD / WixieCD | GitOps — no retry. Refuses with pointer to drift surface. |
| Github Actions / Jenkins / circleci on self-hosted | Honors is_available flag |

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | At least one check rerun (or no failing checks to rerun) |
| 1 | No CI detected on the current repo |
| 2 | All failing checks are on read-only systems (ArgoCD/WixieCD) |
| 3 | Adapter error on every rerun attempt |
