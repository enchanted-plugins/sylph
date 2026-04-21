---
name: workflow-detection
description: Explains the W3 decision tree — how Weaver chooses between GitHub Flow, Trunk-Based, GitFlow, Release Flow, Stacked Diffs, and Unknown. Helpful when a developer asks "why did Weaver pick this branch name?" or wants to override detection via .weaver/workflow-map.yaml.
allowed-tools: Read
---

# workflow-detection

## The decision tree

W3 runs these rules in order. First match wins.

1. **Stacked-diff markers** (`.graphite_config`, `.sl/`, `.git/branchless/`)
   → `stacked-diffs`. Confidence 0.95.
2. **Explicit `.gitflow-config` file** → `gitflow`. Confidence 0.95.
3. **`develop` branch + `release/*` or `hotfix/*` branches** → `gitflow`
   (the legacy pattern). Confidence 0.85.
4. **`release/*` branches + no `develop` + tag cadence ≥ 14 days** →
   `release-flow`. Confidence 0.80.
5. **`release/*` branches + no `develop` + faster cadence** → still
   `release-flow` but lower confidence (0.60).
6. **Median branch age < 3 days AND 1 ≤ active branches < 20** →
   `trunk-based`. Confidence 0.75.
7. **Median branch age 3–14 days OR 2 ≤ active branches < 50** →
   `github-flow`. Confidence 0.70.
8. **Fallback** → `unknown`. Confidence 0.30. The /weaver:workflow-detect
   command surfaces this as "please pick via .weaver/workflow-map.yaml".

## Branch naming per workflow

| Workflow | Pattern | Example |
|----------|---------|---------|
| github-flow | `<type>/<slug>` | `feat/add-oauth-pkce-support` |
| trunk-based | `<user>/<slug>` | `dave/null-session-token` |
| gitflow | `feature/<slug>`, `bugfix/<slug>`, `hotfix/<slug>` | `feature/export-v2` |
| release-flow | `feature/<slug>`, `hotfix/<slug>` | `hotfix/crash-on-signup` |
| stacked-diffs | `<short-topic>` | `cache-refactor` |
| unknown | `wip/<slug>` | `wip/explore-something` |

## Per-subtree overrides

In a monorepo where different teams use different workflows, drop:

```yaml
# .weaver/workflow-map.yaml
packages/mobile: release-flow
packages/web: trunk-based
services/api: github-flow
```

W4 (pr-lifecycle) consults this when opening a PR that only touches files
under one subtree, so a mobile-team PR follows mobile's branching rules
even on a repo where root-level classification picked something else.

## When signals disagree

If you run `/weaver:workflow-detect` and the rationale says something like
"feature-branch pattern + default branch (main), median age 9.0d (GitHub
Flow)" but your team actually uses Trunk-Based with feature flags, the
heuristic is fooled by long-running branches that probably shouldn't exist.
Two fixes:

1. Short-lived your branches and rerun detection after a week.
2. Hardcode it in `.weaver/workflow-map.yaml`:
   ```yaml
   .: trunk-based
   ```

The root-path key `.` forces the whole repo regardless of the tree.

## Confidence below 0.5

When confidence drops below 0.5, W3 returns `unknown` rather than a
low-confidence guess. That's by design — a wrong branch-naming convention
is visible to every reviewer on every PR. Silence is better than noise.

## Pending-actions inbox

The `branch-workflow` PostToolUse hook doesn't create branches — it
classifies the workflow when W2 closes a task boundary and appends a
`branch.suggested` record to:

```
plugins/branch-workflow/state/pending-actions.jsonl
```

Each record carries `{ts, event:"branch.suggested", workflow, dominant_file,
confidence, source_event, executed:false}`. The `/weaver:branch` command is
the consumer — on next invocation it reads the inbox via
`shared/scripts/pending_inbox.py read`, sorts by descending confidence,
presents the top record as the default, and calls
`pending_inbox.py mark <path> <record_ts> branch_name=<name>` to flip the
record to `executed:true` once a branch has been created.

This keeps the loop auto-detect-on / auto-execute-off: W3 always classifies
on every observed boundary, but the branch is created only when the developer
runs `/weaver:branch` (or accepts the default in the next turn). No silent
branch switches — that would violate "silent by default, loud when risky."
