---
name: weaver:status
description: Show the aggregate state of the current branch — active W2 cluster, committed-but-unpushed commits, any open PR, CI status (via ci-reader when installed), reviewer ranking, and merge-queue state.
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/pr_lifecycle.py *), Bash(python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/pr_lifecycle.py *), Bash(gh pr *), Bash(git status *), Bash(git log *), Read(plugins/boundary-segmenter/state/*.json)
---

# /weaver:status

Dashboard for the current branch.

## What it shows

```
Branch:         feature/add-oauth-pkce
Base:           main
Active cluster: 3 events across 2 files (opened 4m ago, distance 0.28)
Pending:        2 commits unpushed
PR:             #142 "feat(auth): add OAuth PKCE flow" — draft
  Checks:       5/7 green, 2 pending (test-integration, build)
  Reviewers:    @dave (blame + CODEOWNERS), @alice (blame), @ben (CODEOWNERS)
  Merge queue:  not enqueued (2 checks outstanding)
```

## Where it reads from

- W2 cluster: `plugins/boundary-segmenter/state/boundary-clusters.json`
- Commits: `git log origin/<base>..HEAD`
- PR state: `gh pr view --json ...` (GitHub) or host-adapter call
- CI: ci-reader plugin's `assembler.pipeline.status.changed` subscription
  or direct `gh api ...check-runs` call
- Reviewers: W4 Path-History Reviewer Routing result cached in
  `state/last-reviewer-suggestion.json`

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Status rendered (even when incomplete sections are shown) |
| 1 | Not in a git repo |
| 2 | No origin remote |
