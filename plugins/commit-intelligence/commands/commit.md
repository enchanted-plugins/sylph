---
name: weaver:commit
description: Draft, validate, and apply a Conventional Commits message for the currently-staged changes. Two-stage pipeline (Sonnet draft → Haiku + Python validate). Safe-amend detection blocks rewriting pushed commits.
---

# /weaver:commit

Commit the currently-staged changes with a Conventional Commits message.

## Usage

```
/weaver:commit                        # draft + validate + apply
/weaver:commit --dry-run              # draft + validate, do not commit
/weaver:commit --amend                # amend the last commit (gated if already pushed)
/weaver:commit --message "..."        # skip Stage 1 drafting, just validate the given message
```

## Flow

```
1. Pre-flight
   ├─ Check `git status --short` — are there staged changes?
   │  If no staged changes: abort with hint to stage first.
   ├─ Check whether --amend targets a pushed commit.
   │  If yes: route through weaver-gate (Hornet-pattern decision-gate).
   └─ Resolve user.signingkey + commit.gpgsign config.

2. Stage 1 — commit-drafter (Sonnet)
   ├─ Collect diff: `git diff --staged`
   ├─ If diff > 1500 tokens, subscribe to the next hornet.change.classified
   │  event for this SHA and use the V1 compressed vector narrative instead.
   ├─ Collect co-author candidates via `git log --follow --format='%an <%ae>' <files>`.
   └─ Emit draft message in Conventional Commits form.

3. Stage 2 — message-validator (Haiku + Python)
   ├─ Run shared/commit_classify.py validate-stdin on the draft.
   ├─ If valid: pass.
   ├─ If invalid: propose a fix mechanically; return verdict { pass | fix-proposed | reject }.
   └─ Surface proposal to user for approval when fix-proposed.

4. Apply
   ├─ Assemble final args: `git commit [-S if signing] -m "<final message>"`.
   ├─ For --amend of unpushed: `git commit --amend -m "..."`.
   └─ For --amend of pushed: abort (weaver-gate blocks; suggest a follow-up commit).

5. Publish events
   ├─ weaver.commit.drafted {branch, sha_preview, type, scope, breaking, message}
   └─ weaver.commit.committed {branch, sha, message, signed, co_authors}
```

## What it will *not* do

- It will not stage files for you. Use `git add` or `/weaver:branch` for that.
- It will not push. Use `/weaver:pr` to open a PR or invoke `git push` directly
  (weaver-gate inspects the push independently).
- It will not amend a pushed commit even with `--yes-i-know` — that path is
  protected-destructive. If you need to fix a pushed commit, the right answer
  is a follow-up commit.
- It will not invoke Opus. Stage 1 is Sonnet, Stage 2 is Haiku + Python.

## Escalations

If Stage 1 emits `# weaver:hint mixed — ...`:
- `/weaver:commit` returns a proposal to route the staged diff to the
  `boundary-segmenter` (W2) for re-clustering into separate commits, rather
  than forcing a single cohesive message on a mixed diff.
- User can override with `--force-single` to accept the mixed message as-is.
  That override is logged but not gated.

If Stage 2 emits `reject`:
- Shows the draft + diagnostics + reason. Commit is NOT applied.
- User must either re-stage with different scope, or re-draft with
  `/weaver:commit --message "..."` to provide an explicit message.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Committed successfully |
| 1 | Nothing staged, aborted |
| 2 | Stage 2 rejected, no commit applied |
| 3 | weaver-gate blocked (amend of pushed commit) |
| 4 | User declined fix proposal |
