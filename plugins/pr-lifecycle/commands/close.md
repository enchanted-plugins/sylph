---
name: weaver:close
description: Close a PR without merging. Useful for abandoned work, accidental opens, or mistakes caught before review. The feature branch is left intact locally and on the remote by default (use --delete-branch to clean up).
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/pr_lifecycle.py *), Bash(python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/pr_lifecycle.py *), Bash(gh pr close *), Bash(git branch --show-current), Bash(git push *)
---

# /weaver:close

Close a PR without merging.

## Usage

```
/weaver:close                        # close PR for current branch
/weaver:close --pr 142               # explicit PR number
/weaver:close --delete-branch        # also delete the feature branch (local + remote)
/weaver:close --reason "superseded by #150"   # add a closing comment
```

## Flow

```
1. Resolve PR number.
2. If --reason is given, post it as a PR comment before closing (so
   reviewers understand the decline).
3. adapter.close_pr(repo, number) — every host adapter implements this.
4. If --delete-branch: weaver-gate gates the remote branch deletion
   through the decision-gate (it's destructive); local branch delete
   is always safe.
5. Publish weaver.pr.closed to state/metrics.jsonl.
```

## When to use

- You realized the change is wrong before anyone reviews.
- The branch is superseded by another PR.
- The work is on pause and you want the PR list clean.

## When NOT to use

- The PR has been approved and CI is green — use `/weaver:merge` instead.
- You want to revert a merged change — use `/weaver:revert`.
- The feature branch still has work to do — leave the PR in draft state.

## Cross-host

| Host | API |
|---|---|
| GitHub | `PATCH /repos/{repo}/pulls/{n}` with `state: closed` |
| GitLab | `PUT /merge_requests/{iid}` with `state_event: close` |
| Bitbucket Cloud | `POST .../pullrequests/{n}/decline` |
| Bitbucket DC | `POST .../pull-requests/{n}/decline?version=...` |
| Azure DevOps | `PATCH .../pullrequests/{n}` with `status: abandoned` |
| Gitea/Forgejo/Codeberg | `PATCH .../pulls/{n}` with `state: closed` |
| CodeCommit | `aws codecommit update-pull-request-status --pull-request-status CLOSED` |
| SourceHut | Refuses — mailing-list threads have no API-level close |

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Closed successfully |
| 2 | Host adapter error |
| 3 | SourceHut (no API close) |
