<!-- Placed in sylph-learning because /sylph:discard is a cross-plugin op over pending state, and sylph-learning is the canonical home for session-level preferences/rollback; a dedicated sylph-undo plugin would be architectural over-reach for now. -->
---
name: sylph:discard
description: Surface every pending branch/commit/PR suggestion Sylph has queued and drop specific ones. Targets the three hook-driven inboxes (pending-actions.jsonl, pending-drafts.jsonl, pending-prs.jsonl) and flips matching records to discarded:true for provenance. Side-effects already committed (created branches, pushed commits, opened PRs) are NOT undone — this only rolls back the suggestion itself and warns when a real artifact exists.
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/discard_surface.py *), Bash(python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/discard_surface.py *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/pending_inbox.py *), Bash(python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/pending_inbox.py *), Read(plugins/branch-workflow/state/pending-actions.jsonl), Read(plugins/commit-intelligence/state/pending-drafts.jsonl), Read(plugins/pr-lifecycle/state/pending-prs.jsonl)
---

# /sylph:discard

Drop a stale or wrong suggestion out of Sylph's pending inbox before it
gets executed — or mark one for provenance after the fact.

## Usage

```
/sylph:discard                                     # list every pending item across the 3 inboxes
/sylph:discard --inbox branch                      # list only branch suggestions
/sylph:discard --inbox commit                      # list only commit drafts
/sylph:discard --inbox pr                          # list only PR drafts
/sylph:discard --inbox branch --ts 2026-04-20T10:00:00Z
/sylph:discard --inbox branch --index 2
/sylph:discard --inbox commit --ts 2026-04-20T10:05:00Z --reason "wrong scope"
/sylph:discard --inbox pr --index 0 --reason "superseded"
```

## The three inboxes

| Inbox | File | Record shape |
|---|---|---|
| `branch` | `plugins/branch-workflow/state/pending-actions.jsonl` | W3 branch suggestions (workflow, dominant_file, confidence) |
| `commit` | `plugins/commit-intelligence/state/pending-drafts.jsonl` | W1 Conventional-Commits drafts (type, scope, subject) |
| `pr` | `plugins/pr-lifecycle/state/pending-prs.jsonl` | W4 PR drafts (title, body, reviewers) |

## Selection modes

Exactly one selection is required when discarding (both may be given
together only when they agree — prefer `--ts` for cross-session stability):

- `--ts <iso>` — exact timestamp match. Stable across re-runs because
  the ts is the natural key on every inbox record.
- `--index <n>` — 0-based index into the filtered list shown by
  `/sylph:discard --inbox <name>`. Convenient but session-local: if a
  new hook appends while you're deciding, indexes can shift.

If neither `--ts` nor `--index` is given, nothing is discarded — you
get the listing and exit 0.

## What it actually does

1. Runs `discard_surface.py list [--inbox <name>]` to produce envelopes.
2. Renders the list with index, summary, ts, confidence.
3. If `--ts` or `--index` is supplied, resolves the target record:
   - `--index` → calls `discard_surface.py resolve --inbox X --index N` to
     turn it into a `(path, ts)` pair.
   - `--ts` → scans the listing for the exact match.
4. Shells out to `pending_inbox.py discard <path> <ts> [reason="..."]`
   which atomically flips `discarded:true, discarded_at:<now>` on the
   matching record.
5. Surfaces a warning if the record was already `executed:true` with a
   side-effect field:

   | Inbox | Field | Warning |
   |---|---|---|
   | `branch` | `branch_name` | "branch already created; delete manually with `git branch -D <name>` if needed" |
   | `commit` | `sha` | "commit already exists; use `/sylph:reset` or `git reset` to undo" |
   | `pr` | `pr_number` | "PR already drafted; close it via the host UI or `gh pr close <n>`" |

## Idempotence

Re-discarding an already-discarded record is a no-op — exit 0 with a
"already discarded" note. Unknown `--ts` exits 1 with an error message.
Unknown `--inbox` exits 2.

## Discard record shape

```json
{
  "ts": "2026-04-20T10:00:00Z",
  "event": "branch.suggested",
  "workflow": "github-flow",
  "dominant_file": "src/auth.py",
  "confidence": 0.85,
  "executed": false,
  "discarded": true,
  "discarded_at": "2026-04-20T11:12:34Z",
  "discard_reason": "wrong workflow for this repo"
}
```

`read_pending` excludes records where `discarded:true`, so the next
`/sylph:branch` / `/sylph:commit` / `/sylph:pr` invocation never
sees the dropped suggestion again.

Discarded records remain on disk as terminal provenance so W5's EMA
can eventually read them as a negative signal (future work; see the
`# TODO: emit discard signal to sylph-learning for W5 EMA` marker in
`shared/scripts/pending_inbox.py`).

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Listing printed, or discard succeeded (including the idempotent no-op) |
| 1 | `--ts` or `--index` did not resolve to any pending record |
| 2 | Bad CLI args (unknown `--inbox`, malformed flags) |
