---
name: weaver:commit
description: Draft, validate, and apply a Conventional Commits message for the currently-staged changes. Prefers the pending-drafts inbox (populated by the commit-intelligence hook when W2 closes a task boundary) as the seed for the Sonnet draft. Two-stage pipeline (Sonnet draft → Haiku + Python validate). Safe-amend detection blocks rewriting pushed commits.
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/pending_inbox.py *), Bash(python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/pending_inbox.py *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/commit_classify.py *), Bash(python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/commit_classify.py *), Bash(git diff *), Bash(git status *), Bash(git log *), Bash(git commit *), Read(plugins/commit-intelligence/state/pending-drafts.jsonl)
---

# /weaver:commit

Commit the currently-staged changes with a Conventional Commits message. When
the `commit-intelligence` hook listener has queued a `commit.drafted` record
on the pending-drafts inbox, use that as the seed for Stage 1 drafting — the
suggested type and file context come from the W2 cluster the hook observed.
Otherwise compute them fresh from `git diff --staged`.

## Usage

```
/weaver:commit                        # consume top pending draft (if any), else draft from diff; validate; apply
/weaver:commit --dry-run              # draft + validate, do not commit
/weaver:commit --amend                # amend the last commit (gated if already pushed)
/weaver:commit --message "..."        # skip Stage 1 drafting, just validate the given message (ignores inbox)
/weaver:commit --no-pending           # skip the inbox even when it has entries
```

## Flow

```
1. Pre-flight
   ├─ Check `git status --short` — are there staged changes?
   │  If no staged changes: abort with hint to stage first.
   ├─ Check whether --amend targets a pushed commit.
   │  If yes: route through weaver-gate (Hornet-pattern decision-gate).
   └─ Resolve user.signingkey + commit.gpgsign config.

2. Pending inbox (unless --message or --no-pending)
   ├─ Run `shared/scripts/pending_inbox.py read plugins/commit-intelligence/state/pending-drafts.jsonl`.
   │  Output is a JSON array of executed=false records, sorted by descending
   │  confidence (where present), else FIFO.
   ├─ If empty: skip to step 3 (pure-diff drafting).
   └─ If non-empty: surface the top record to the developer:
        • suggested_type + dominant_file + files + event_count
        • source_event.ts + source_event.closed_cluster.id for traceability
      Ask: accept / modify / discard.
      • Accept       → pass {suggested_type, files, dominant_file} to Stage 1
                       as a seed; Sonnet still drafts the subject + body from
                       the staged diff but prefers the hinted type.
      • Modify       → override suggested_type / scope, then Stage 1.
      • Discard      → mark executed with `discarded:true` (no commit) and exit 0.

3. Stage 1 — commit-drafter (Sonnet)
   ├─ Collect diff: `git diff --staged`.
   ├─ If a pending record was accepted, pass its `suggested_type` and `files`
   │  as hints; Sonnet may override if the staged diff obviously disagrees
   │  (e.g. the hook suggested `chore` but the diff touches `src/**`).
   ├─ If diff > 1500 tokens, subscribe to the next hornet.change.classified
   │  event for this SHA and use the V1 compressed vector narrative instead.
   ├─ Collect co-author candidates via `git log --follow --format='%an <%ae>' <files>`.
   └─ Emit draft message in Conventional Commits form.

4. Stage 2 — message-validator (Haiku + Python)
   ├─ Run shared/scripts/commit_classify.py validate-stdin on the draft.
   ├─ If valid: pass.
   ├─ If invalid: propose a fix mechanically; return verdict { pass | fix-proposed | reject }.
   └─ Surface proposal to user for approval when fix-proposed.

5. Apply
   ├─ Assemble final args: `git commit [-S if signing] -m "<final message>"`.
   ├─ For --amend of unpushed: `git commit --amend -m "..."`.
   └─ For --amend of pushed: abort (weaver-gate blocks; suggest a follow-up commit).

6. Mark the consumed draft executed (if one was accepted):
   `shared/scripts/pending_inbox.py mark plugins/commit-intelligence/state/pending-drafts.jsonl <record_ts> sha=<sha>`

7. Publish events
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
- It will not silently honor the inbox suggestion when the developer passed
  `--message "..."`. Explicit message wins; the inbox record is left
  untouched for a future invocation.

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
| 0 | Committed successfully (or pending draft discarded) |
| 1 | Nothing staged, aborted |
| 2 | Stage 2 rejected, no commit applied |
| 3 | weaver-gate blocked (amend of pushed commit) |
| 4 | User declined fix proposal |
