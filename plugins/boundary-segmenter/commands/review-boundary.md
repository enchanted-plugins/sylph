---
name: sylph:review-boundary
description: Review the oldest pending W2 boundary escalation. Loads the pending record from escalations.jsonl, hands the cluster previews to the Opus boundary-detector agent for judgment, and records the verdict to escalation-verdicts.jsonl. Non-destructive; verdicts feed W5 Gauss Learning.
allowed-tools: Read, Bash(git status *), Bash(git diff --stat *), Bash(git log --oneline -n 10), Bash(jq *), Bash(wc *), Bash(tail *), Bash(date *)
---

# /sylph:review-boundary

Resolve a low-confidence W2 boundary by consulting the Opus
`boundary-detector` agent. Sylph's PostToolUse hook appends an escalation
record whenever the Jaccard-Cosine segmenter emits a boundary with
`confidence < SYLPH_BOUNDARY_CONFIDENCE_THRESHOLD` (default 0.7) or the
distance lands in the `±uncertainty_band` around θ. This slash-command is
the human-invoked bridge between that escalation and the agent — the hook
itself never calls Opus (hooks are advisory and must not make network
calls).

## Usage

```
/sylph:review-boundary              # pop the oldest pending escalation
/sylph:review-boundary --list       # show pending escalations without resolving
/sylph:review-boundary --ts <TS>    # resolve a specific escalation by ts
```

## What it does

1. Reads `plugins/boundary-segmenter/state/escalations.jsonl`.
2. Filters out entries whose `ts` already appears in
   `plugins/boundary-segmenter/state/escalation-verdicts.jsonl` — the
   verdicts file is the idempotency fence.
3. Picks the oldest unresolved escalation (or the one matching `--ts`).
4. Assembles the agent input — `closed_cluster_preview`,
   `active_cluster_now`, `distance`, `threshold`, `confidence`, and the
   `reason` code — and hands it to the Opus `boundary-detector` agent
   (see `plugins/boundary-segmenter/agents/boundary-detector.md`).
5. Captures the agent's JSON verdict (`{"decision": "close" | "absorb",
   "rationale": "..."}`).
6. Appends a verdict record to
   `plugins/boundary-segmenter/state/escalation-verdicts.jsonl`:

   ```json
   {
     "ts": "<iso-8601 now>",
     "event": "sylph.boundary.escalation.resolved",
     "source_escalation_ts": "<ts of the escalation>",
     "decision": "close" | "absorb",
     "rationale": "<agent's one-liner>",
     "agent": "boundary-detector"
   }
   ```

## Output

Prints the agent's decision + rationale to stdout, plus the path of the
verdict record for the audit trail. If no pending escalations exist,
exits 0 with `no pending escalations`.

## What it will *not* do

- It will not modify `boundary-events.jsonl`. The boundary event has
  already been emitted to downstream plugins (branch-workflow,
  commit-intelligence, pr-lifecycle) with `escalated:true`. Those
  plugins are responsible for reading the verdicts feed and correcting
  their own pending-action records if they care about the Opus decision.
- It will not auto-rewrite git history. If the verdict flips a boundary
  from `close` to `absorb` after a commit has already been drafted, the
  correction routes through `/sylph:commit --amend-last` (which itself
  goes through `sylph-gate` per the destructive-op contract).
- It will not call any non-Sylph remote. Opus judgment is the only
  network surface this command touches.

## Why a skill, not a hook

PostToolUse hooks are advisory and must be silent + fast. Calling Opus
from a hook would block the user's next tool-use for seconds and violate
the "silent by default" behavioral contract. The escalation marker is
the asynchronous handoff: W2 surfaces the uncertainty, the developer
(or an automated follow-up) invokes this skill when they're ready to
pay the judgment cost.

## Exit codes

| Code | Meaning |
|------|---------|
| 0    | Verdict captured (or no pending escalations) |
| 1    | Escalations file missing or corrupt |
| 2    | Agent failed to return a parseable verdict |

## Related

- `plugins/boundary-segmenter/agents/boundary-detector.md` — the Opus
  agent that renders the verdict.
- `plugins/boundary-segmenter/hooks/post-tool-use/boundary-segment.sh` —
  the PostToolUse hook that emits escalations.
- `shared/constants.sh` — tune `SYLPH_BOUNDARY_CONFIDENCE_THRESHOLD`
  via env override.
