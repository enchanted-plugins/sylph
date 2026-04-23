---
name: sylph:merge
description: Merge the current branch's PR with the chosen strategy. Defaults to squash when the target branch is trunk-based/github-flow (short-lived feature branches); to merge-commit for gitflow/release-flow (long-lived branches that need history preservation). Respects merge queues — when one is configured, enqueues via auto-merge rather than merging directly.
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/pr_lifecycle.py *), Bash(python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/pr_lifecycle.py *), Bash(gh pr *), Bash(git branch --show-current), Bash(git remote get-url *), Read(plugins/branch-workflow/state/workflow-map.json)
---

# /sylph:merge

Merge the PR for the current branch.

## Usage

```
/sylph:merge                      # pick strategy from W3 workflow detection
/sylph:merge --squash             # force squash
/sylph:merge --rebase             # force rebase
/sylph:merge --merge-commit       # force 3-way merge commit
/sylph:merge --auto               # enable auto-merge (enqueue on merge queue)
/sylph:merge --pr 142             # explicit PR number; defaults to current branch's PR
/sylph:merge --dry-run            # show the planned call without executing
```

## Strategy defaults (when unspecified)

Inferred from `/sylph:workflow-detect`:

| Workflow | Default strategy | Why |
|---|---|---|
| github-flow | `squash` | Short-lived feature branches; clean linear history |
| trunk-based | `squash` | Same — branches measured in hours |
| gitflow | `merge-commit` | Preserve history for release branches |
| release-flow | `merge-commit` | Same |
| stacked-diffs | `rebase` | Graphite / Sapling stack integrity |
| unknown | `merge-commit` | Conservative — never rewrites history |

## Flow

```
1. Resolve PR number (arg OR `gh pr view --current`).
2. Detect workflow via W3 unless --strategy given.
3. Check CI status (ci-reader):
   ├─ green + approved → proceed
   ├─ pending        → ask user: wait / enqueue auto-merge / force-merge
   └─ failing        → refuse unless --force-merge
4. Decide enqueue vs direct merge:
   ├─ --auto flag OR repo has merge queue + CI pending → adapter.enqueue_merge()
   └─ else adapter.merge_pr(strategy)
5. Publish sylph.pr.merged OR sylph.pr.enqueued to state/metrics.jsonl.
6. Offer to delete the local feature branch (unless user declines).
```

## Guardrails

- **Never merges with failing required checks.** `--force-merge` bypasses
  but routes through sylph-gate as a destructive-op for audit.
- **Protected branch rules honored.** If GitHub rejects because a required
  review is missing, surfaces the reason verbatim rather than retrying.
- **Merge-queue-configured repos auto-enqueue by default** — direct merge
  would skip required checks.
- **Stacked-diff branches:** refuses to merge via normal flow; points at
  `gt submit` / `sl pr land` / `git-branchless submit` for the stack-aware
  tool that already owns it.

## Cross-host

Works via the host adapter resolved from `git remote get-url origin`:

| Host | API used |
|---|---|
| GitHub | `PUT /repos/{owner}/{repo}/pulls/{n}/merge` (urllib) or `gh pr merge` |
| GitLab | `PUT /projects/{id}/merge_requests/{iid}/merge` |
| Bitbucket Cloud | `POST /repositories/{ws}/{slug}/pullrequests/{n}/merge` |
| Bitbucket DC | `POST /projects/{key}/repos/{slug}/pull-requests/{n}/merge?version=...` |
| Azure DevOps | `PATCH .../pullrequests/{n}` with `status: completed` |
| Gitea / Forgejo / Codeberg | `POST /repos/{owner}/{repo}/pulls/{n}/merge` |
| AWS CodeCommit | `aws codecommit merge-pull-request-by-{strategy}` |
| SourceHut | Refuses — merges happen via maintainer's `git am` |

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Merged successfully (or enqueued) |
| 1 | CI failing / no approvals / protected-branch block |
| 2 | Stacked-diff branch — use stack tool |
| 3 | Host adapter error |
