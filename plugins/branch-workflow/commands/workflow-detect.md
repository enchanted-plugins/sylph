---
name: sylph:workflow-detect
description: Run W3 Workflow-Pattern Classifier on the current repo and show which branching model Sylph detected — GitHub Flow / Trunk-Based / GitFlow / Release Flow / Stacked Diffs / Unknown. Shows the signals and the rationale.
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/workflow_detect.py *), Bash(python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/workflow_detect.py *), Read(**/.sylph/workflow-map.yaml)
---

# /sylph:workflow-detect

Show Sylph's view of your repo's branching model.

## What it does

1. Walks the repo: `git for-each-ref`, `git symbolic-ref HEAD`, tag
   cadence, detection of `.gitflow-config` / `.graphite_config` / `.sl/` /
   `.git/branchless/`.
2. Runs the weighted decision tree in `shared/scripts/workflow_detect.py`.
3. Prints a JSON report:

```json
{
  "workflow": {
    "label": "github-flow",
    "confidence": 0.7,
    "rationale": ["feature-branch pattern + default branch (main), median age 4.2d"],
    "signals": { ... }
  },
  "subtree_overrides": { "packages/mobile": "release-flow" }
}
```

## When to use it

- Before `/sylph:commit` if you're curious which branch-naming convention
  Sylph will use.
- When Sylph picks a branch name you disagree with — the signals reveal
  which heuristic fired.
- When you've just adopted a stacked-diff tool (Graphite / Sapling /
  git-branchless) and want to confirm W3 noticed.

## Overriding

Drop `.sylph/workflow-map.yaml` at repo root:

```yaml
packages/mobile: release-flow
packages/web: trunk-based
services/api: github-flow
```

W3 honors per-subtree overrides when W4 opens PRs that only touch files
under a given subtree. Root-level classification still runs.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Detection complete (even for `unknown`) |
| 3 | Usage error |
