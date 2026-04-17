---
name: weaver:dry-run
description: Execute a git-flavored command in dry-run mode — all plumbing, zero writes. Useful for previewing what Weaver would do without touching remotes or rewriting history.
---

# /weaver:dry-run

Preview what a Weaver-driven git operation *would* do, without actually writing
to the local repo or any remote.

## Usage

```
/weaver:dry-run git push origin feature/auth-refactor
/weaver:dry-run git rebase -i main
/weaver:dry-run weaver commit
```

## What it does

1. Takes the full command that follows `/weaver:dry-run`.
2. Routes it through `weaver-gate`'s destructive-op classifier (`shared/scripts/destructive_patterns.py`).
3. Emits a plan summary: classification, recovery window, the reverse command
   (if we can suggest one), and the intended side-effects.
4. **Never** executes the command.

## Why

Production git operations that rewrite history or delete refs are hard to
reverse. Weaver's default is to confirm before destructive ops through the
decision-gate. Dry-run is the pre-confirmation preview: see what the gate
would say before you commit to invoking the real command.

## What it will *not* do

- It will not `git push`, even with `--dry-run` set as a flag to git itself.
- It will not invoke the W1 commit-drafter, W2 boundary segmenter, W4 reviewer
  router, or any LLM. This is a rules-only preview.
- It will not write to `plugins/weaver-gate/state/audit.jsonl` — dry-run
  inspections are not audited (the real call will be).
