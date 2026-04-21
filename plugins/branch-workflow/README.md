# branch-workflow

**Detects your branching model and drives branch creation per task boundary.**

Engine: **W3 — Workflow-Pattern Classifier.**

Infers active workflow (GitHub Flow / Trunk-Based / GitFlow / Release Flow / Stacked Diffs) from branch graph, protection rules, config files (`.gitflow-config`, `.graphite_config`, `.sl/`, `.git/branchless/`), and release cadence in `git tag`. Handles multi-workflow monorepos per-subtree via CODEOWNERS or `.weaver/workflow-map.yaml`.

## Install

Part of the [Weaver](../..) bundle:

```
/plugin marketplace add enchanted-plugins/weaver
/plugin install full@weaver
```

Standalone: `/plugin install branch-workflow@weaver`.

## Components

| Type | Name | Role |
|------|------|------|
| Skill | workflow-detection | W3 reasoning skill |
| Command | `/weaver branch` | Explicit branch creation |
| Command | `/weaver workflow-detect` | Run W3 + show reasoning |
| Script | workflow_detect.py | Feature vector + decision tree |

## Hook chain

`branch-workflow` registers a `PostToolUse(Edit|Write|MultiEdit)` hook (`hooks/post-tool-use/on-boundary.sh`) that tails `plugins/boundary-segmenter/state/boundary-events.jsonl` from its persisted byte offset in `state/listener-offset.json`. For each new `weaver.task.boundary.detected` line, it runs `shared/scripts/workflow_detect.py` and appends a `branch.suggested` record to `state/pending-actions.jsonl`. The `/weaver:branch` skill picks up pending actions on next invocation — auto-detection is on, auto-execution stays gated to honor "silent by default, loud when risky."

Architecture note: **independent listener (Option 1)** — loose coupling over deterministic fire order; each plugin owns its own offset.

## Cross-plugin

- **Consumes** `weaver.task.boundary.detected` to drive branch creation.
- **Publishes** `weaver.workflow.detected { subtree, label, confidence }`.

Full architecture: [../../docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md#layer-7-branching--workflow-engine-w3).
