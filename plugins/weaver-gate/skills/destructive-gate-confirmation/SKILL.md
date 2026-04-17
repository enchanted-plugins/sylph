---
name: destructive-gate-confirmation
description: Surfaces the decision-gate to the user when a destructive git operation is detected, pausing the session for explicit confirmation before the command runs. Invoked by weaver-gate's PreToolUse hook when a Bash call is classified destructive or protected-destructive.
allowed-tools: Read, Bash(python3 ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/destructive_patterns.py *)
---

# destructive-gate-confirmation

## When this skill fires

Whenever a `PreToolUse(Bash)` hook blocks with exit 2 because the command
matched a destructive-op pattern. The hook writes a block reason to stderr
describing the operation; this skill's job is to surface that to the user and
route the confirmation decision.

## Classification tiers

Three outcomes, matching `shared/scripts/destructive_patterns.py`:

1. **SAFE** (classification = `safe`) — hook exits 0, skill does not fire, command runs normally.
2. **DESTRUCTIVE** — force-push, interactive rebase of pushed commits, reset --hard past pushed tip, branch -D of unmerged, remote branch deletion, tag -d. Can be bypassed with explicit user confirmation. Default: require confirmation.
3. **PROTECTED-DESTRUCTIVE** — `git clean -fdx` (irrecoverable: untracked + ignored deletion). Also force-push to a protected branch when capability-memory can resolve the branch-protection rules. **Never bypassed.** User must alter the command.

## The confirmation prompt

For DESTRUCTIVE:

```
⚠️  Destructive git operation detected

  Command:   <the git command>
  Op:        <git push --force | git filter-branch | ...>
  Reason:    <human explanation>
  Recovery:  <N> day(s) from reflog; see <reverse command> to undo

Options:
  1. Proceed (you're confident this is correct)
  2. Swap in the safer alternative (e.g. --force-with-lease)
  3. Cancel

Respond with 1, 2, or 3.
```

For PROTECTED-DESTRUCTIVE:

```
🛑  Protected-destructive operation blocked

  Command:  <the git command>
  Op:       <git clean -fdx | force-push to protected branch>
  Reason:   <human explanation>

This operation cannot be bypassed from within Weaver. If you genuinely
intend to proceed, invoke git directly outside the session.

Options:
  1. Cancel (recommended)
  2. Rewrite the command (omit -x to exclude ignored files; push to
     a different branch; etc.)
```

## What to do when the user picks an option

- **1 (proceed)**: emit an event `weaver.destructive.confirmed` and tell the user to re-run the original command with `--yes-i-know` appended. The hook has an escape hatch for that flag.
- **2 (swap)**: propose the concrete safer command as an edit. Example: `git push --force origin main` → `git push --force-with-lease origin main`. Let the user copy-paste or accept the proposal.
- **3 (cancel)** or any protected-destructive: stop. Do not re-run.

## Audit trail

The hook has already written a record to `plugins/weaver-gate/state/audit.jsonl`
with the blocked classification, command, recovery window, and timestamp. When
the user confirms via option 1, append a second record with `{outcome:
"confirmed", at: <ts>}` to the same file via `shared/scripts/atomic_json.py`'s
`append_jsonl`. Never overwrite prior records — append-only.

## What this skill does *not* do

- It does not run any git command itself. It proposes; the user disposes.
- It does not invoke any LLM. Classification is already done by the Python
  rules module; the skill's job is the user-facing surface only.
- It does not write to `audit.jsonl` in dry-run mode (the `weaver:dry-run`
  command path bypasses this skill).
