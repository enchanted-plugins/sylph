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

## Cross-plugin

- **Consumes** `weaver.task.boundary.detected` to drive branch creation.
- **Publishes** `weaver.workflow.detected { subtree, label, confidence }`.

Full architecture: [../../docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md#layer-7-branching--workflow-engine-w3).
