---
name: weaver:branch
description: Create or switch to a new branch for the current task boundary, named per the detected workflow (GitHub Flow uses type/slug, Trunk-Based uses user/slug, etc.). Prefers a suggestion from the pending-actions inbox when the hook listener has queued one; otherwise reads the active W2 cluster to slug the branch.
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/workflow_detect.py *), Bash(python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/workflow_detect.py *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/pending_inbox.py *), Bash(python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/pending_inbox.py *), Bash(git branch *), Bash(git checkout *), Bash(git status *), Read(plugins/boundary-segmenter/state/boundary-clusters.json), Read(plugins/branch-workflow/state/pending-actions.jsonl)
---

# /weaver:branch

Create and check out a branch named per the repo's detected workflow. When the
`branch-workflow` hook listener has already queued a `branch.suggested` record
on the pending-actions inbox, prefer that — it means W3 already saw a closed
task boundary and pre-classified the workflow. Otherwise fall through to the
manual slug flow.

## Usage

```
/weaver:branch                                # consume top pending suggestion, else infer from active W2 cluster
/weaver:branch "add oauth pkce support"       # explicit slug (ignores pending inbox)
/weaver:branch --type fix "null session token"  # override Conventional Commits type
/weaver:branch --from-boundary <boundary-id>  # name based on a closed cluster
/weaver:branch --no-pending                   # skip the inbox even when it has entries
/weaver:branch --dry-run ...                  # show the chosen name, do not create
```

## Flow

```
1. Read the pending-actions inbox (unless --no-pending or an explicit slug was given):
   ├─ Run `shared/scripts/pending_inbox.py read plugins/branch-workflow/state/pending-actions.jsonl`.
   │  Output is a JSON array of executed=false records, sorted by descending
   │  confidence. Element 0 is the default suggestion.
   ├─ If the array is empty: fall through to step 2 (manual flow).
   └─ If non-empty: present the top record as the default:
        • workflow label + confidence
        • dominant_file from the closed cluster
        • files list + event_count from source_event context
        • `source_event.ts` + `source_event.closed_cluster.id` for traceability
      Ask the developer to accept, modify (edit slug/type), or discard.
      • Accept       → proceed to step 3 with the suggestion's workflow + dominant_file-derived slug.
      • Modify       → proceed to step 3 with the developer's substitutions; still mark executed after.
      • Discard      → mark executed with `discarded:true` (no branch created) and exit 0.
      • Multi-pending → if >1 records, show them all and let the developer pick by index.
2. Manual flow (no pending suggestion or --no-pending):
   ├─ Detect workflow via `shared/scripts/workflow_detect.py detect`.
   ├─ Pick the slug:
   │   ├─ explicit arg wins
   │   ├─ else read active cluster from
   │   │  `plugins/boundary-segmenter/state/boundary-clusters.json` and extract
   │   │  a slug from the dominant file path + top token
   │   └─ else abort with hint to pass an explicit slug
   └─ Pick the type:
       ├─ --type flag wins
       ├─ else default per workflow ('feat' for github-flow / trunk-based,
       │  'feature' for gitflow, etc.)
       └─ stacked-diffs ignores type (short topic names only)
3. Call `shared/scripts/workflow_detect.py suggest-branch <workflow> <type> <slug>`.
4. Check out a new branch with that name (unless --dry-run):
   `git checkout -b <name>`
5. Mark the consumed record executed (if the branch came from the inbox):
   `shared/scripts/pending_inbox.py mark plugins/branch-workflow/state/pending-actions.jsonl <record_ts> branch_name=<name>`
6. Publish `weaver.branch.created` to state/metrics.jsonl.
```

## Guardrails

- If the working tree is dirty when invoked on `main`/`master`/`trunk`,
  refuse and suggest the user either commit with `/weaver:commit` or
  stash first. Creating a branch carries uncommitted work along, and
  that confuses the per-boundary cluster ownership story.
- Never force-delete an existing branch. If the suggested name collides,
  append `-2`, `-3`, etc., and report the collision.
- For stacked-diff tools (Graphite / Sapling / git-branchless), prefer
  the tool's own branch command when it's installed (`gt create`,
  `sl commit`, `git-branchless submit`). W3 detects these; W4's PR
  lifecycle handles stacking.
- A pending suggestion with `confidence < 0.5` is shown with a warning
  banner — the developer should normally override rather than accept.
  The W3 hook writes those low-confidence records deliberately; the
  final decision belongs to the human.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Branch created and checked out (or suggestion discarded) |
| 1 | Dirty tree on trunk (aborted with hint) |
| 2 | No slug provided and active cluster empty and inbox empty |
| 3 | Git error (e.g., name collision after retries) |
