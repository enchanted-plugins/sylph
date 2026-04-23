---
name: sylph:revert
description: Safely revert a commit (or merge commit) by creating a new revert commit — never by rewriting history. Works for pushed and unpushed commits. For merge commits, picks the correct parent via `-m 1`. The revert itself goes through /sylph:commit so it gets a proper Conventional Commits message.
allowed-tools: Bash(git log --oneline *), Bash(git show *), Bash(git revert *), Bash(git cat-file *), Read(plugins/commit-intelligence/*)
---

# /sylph:revert

Undo a commit by creating an inverse commit. Never rewrites history.

## Usage

```
/sylph:revert                     # revert HEAD (the last commit on the current branch)
/sylph:revert abc1234             # revert a specific commit
/sylph:revert HEAD~3              # revert 3 commits ago
/sylph:revert abc1234..def5678    # revert a range (newest first, chain of commits)
/sylph:revert --merge abc1234     # revert a merge commit via `-m 1` (first parent)
/sylph:revert --no-edit           # don't open editor; use auto-generated message
```

## Flow

```
1. Resolve target SHA(s).
2. Detect if the commit is a merge commit (2+ parents via `git cat-file -p`).
   ├─ Yes → require --merge flag (otherwise `git revert` will refuse)
   └─ No  → standard revert
3. Run `git revert --no-commit <sha>`.
4. Hand off the staged revert to /sylph:commit, which drafts a
   Conventional Commits message of the shape:
     "revert: <original subject>"
     + body: "This reverts commit <sha>. <reason>"
5. /sylph:commit fires normally — W1 Stage 1 (Sonnet) + Stage 2 (Haiku).
6. Final commit lands on the current branch.
7. Publish sylph.commit.reverted to state/metrics.jsonl.
```

## Safe by design

- `git revert` creates NEW commits. It does not rewrite history. Safe
  for pushed commits.
- Merge-commit reverts need `-m 1` to say "revert the merged content,
  keep the first-parent side." Sylph handles that automatically when
  `--merge` is passed.
- Reverting a range creates one revert commit per source commit (by
  default newest-first). Use `--squash-range` if you want a single
  revert commit for the whole range.

## Compared to sylph-gate's gated ops

| Operation | Rewrites history? | sylph-gate? |
|---|---|---|
| `/sylph:revert <sha>` | **No** — new commit | No gate, safe by default |
| `git reset --hard <sha>` | Yes | Gated (destructive) |
| `git rebase -i <past-pushed>` | Yes | Gated (destructive) |
| `git commit --amend` on pushed | Yes | Gated (destructive) |

Revert is the first-class way to "undo" in Sylph's mental model.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Revert commit created |
| 1 | SHA not found / not reachable |
| 2 | Merge commit without `--merge` flag |
| 3 | Revert conflicts — user must resolve + continue |
