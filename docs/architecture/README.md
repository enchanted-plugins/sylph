# Sylph Architecture

> Auto-generated from codebase by `generate.py`. Run `python docs/architecture/generate.py` to regenerate.

## Interactive Explorer

Open [index.html](index.html) in a browser to explore the architecture interactively with tabbed Mermaid diagrams and plugin component cards.

## At a Glance

**9 sub-plugins. 5 algorithms (W1–W5). 5 agents. 6 hook bindings. 30 tests.**

Sylphs are silk-spinners — branches are threads, merges stitch them into a coherent history. Sylph covers the full git-flow arc: boundary detection → branch → commit → PR → CI observation → learning.

## Diagrams

| Diagram | File | Description |
|---------|------|-------------|
| High Level | [highlevel.mmd](highlevel.mmd) | 9 sub-plugins across SessionStart / PreToolUse / PostToolUse / PreCompact |
| Session Lifecycle | [lifecycle.mmd](lifecycle.mmd) | Load priors → gate destructive ops → segment → draft → push → observe |
| Data Flow | [dataflow.mmd](dataflow.mmd) | Cross-plugin events via enchanted-mcp event bus |
| Hook Bindings | [hooks.mmd](hooks.mmd) | Hook binding map with matchers and timeouts per sub-plugin |

## Sub-plugin Summary

| Sub-plugin | Hook Phase | Matcher | Timeout | Algorithm |
|------------|-----------|---------|---------|-----------|
| capability-memory | SessionStart | * | 10s | — |
| sylph-learning | SessionStart | * | 5s | W5 |
| sylph-gate | PreToolUse | Bash | 5s | — |
| boundary-segmenter | PostToolUse | Edit\|Write\|MultiEdit | 10s | W2 |
| boundary-segmenter | PreCompact | * | 5s | W2 |
| sylph-learning | PreCompact | * | 5s | W5 |
| commit-intelligence | (agents only) | — | — | W1 |
| branch-workflow | (skill, event-driven) | — | — | W3 |
| pr-lifecycle | (skill, event-driven) | — | — | W4 |
| ci-reader | (skill, event-driven) | — | — | — |
| full | meta-plugin (bundles above) | — | — | — |

## Algorithms (W1–W5)

| Code | Name | Where |
|------|------|-------|
| W1 | Myers-Diff Conventional Classifier | `shared/scripts/commit_classify.py` |
| W2 | Jaccard-Cosine Boundary Segmentation | `shared/scripts/boundary_segment.py` |
| W3 | Workflow-Pattern Classifier | `shared/scripts/workflow_detect.py` |
| W4 | Path-History Reviewer Routing | `shared/scripts/reviewer_route.py` |
| W5 | Gauss Learning (EMA Accumulation) | `shared/scripts/gauss_learning.py` |

Full derivations: [docs/science/README.md](../science/README.md).

## Agents

| Agent | Tier | Role |
|-------|------|------|
| commit-drafter | Sonnet | W1 Stage 1 — draft conventional-commit message from diff |
| message-validator | Haiku | W1 Stage 2 — validate spec + length + safe-amend |
| boundary-detector | Opus | W2 judgment on confidence-edge clusters (±0.10 band) |
| pr-description-crafter | Opus | W4 PR description from boundary cluster |
| conflict-resolver | Opus | W4 merge-conflict proposals |

## Execution Order

```
1. SessionStart
   ├─ capability-memory:   load provider registry, probe GitLab self-managed (10s)
   └─ sylph-learning:     load Gauss priors from learnings.json (5s)

2. PreToolUse (Bash)
   └─ sylph-gate:         classify destructive git ops, request confirmation (5s)

3. PostToolUse (Edit|Write|MultiEdit)
   └─ boundary-segmenter:  online clustering; fire boundary events (10s)

4. PreCompact
   ├─ boundary-segmenter:  checkpoint cluster state (5s)
   └─ sylph-learning:     persist EMA learnings (5s)

5. Event-driven (enchanted-mcp bus)
   ├─ branch-workflow:     auto-create branch on boundary event, per detected workflow
   ├─ commit-intelligence: draft conventional commit via W1 pipeline
   ├─ pr-lifecycle:        state machine — draft → ready → review → merge
   └─ ci-reader:           observe CI status across 8 systems, publish observations
```

## Quantifiable Assets

| Class | Count |
|-------|-------|
| Sub-plugins | 9 (+ `full` bundle) |
| Agents | 5 |
| Hook scripts | 6 |
| Shared script LOC | 5,300+ |
| Canonical commit types | 11 (feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert) |
| Workflow classes | 6 (stacked-diffs, gitflow, release-flow, trunk-based, github-flow, unknown) |
| Git-host adapters | 9 (GitHub, GitLab, Bitbucket, Azure DevOps, Gitea, CodeCommit, SourceHut, Codeberg) |
| CI adapters | 8 (GitHub Actions, GitLab CI, CircleCI, Jenkins, Buildkite, Drone, Tekton, ArgoCD) |
| Destructive-op rules | 14 (force-push, filter-branch, reset-hard, branch/remote/tag delete, etc.) |
| Tests | 30 |

## State Files

| File | Written by | Purpose |
|------|-----------|---------|
| `audit.jsonl` | sylph-gate | Destructive-op decisions |
| `boundary-clusters.json` | boundary-segmenter | Live cluster state |
| `learnings.json` | sylph-learning | EMA priors (commit style, branch naming, PR turnaround) |
| `capability-registry.json` | capability-memory | Host capability probe results |
| `session-cache/` | pr-lifecycle, ci-reader | Adapter response cache |

## Test Coverage

```
tests/
├── boundary-segmenter/   3 tests (boundary-fires, cohesive-cluster, hook-flow)
├── branch-workflow/      3 tests (branch-naming, classify-repos, monorepo-overrides)
├── capability-memory/    2 tests (registry-schema, session-start-loader)
├── ci-reader/            2 tests (detect-systems, stub-adapters)
├── commit-intelligence/  3 tests (invalid-commits, valid-commits, warnings)
├── integration/          3 tests (edit-to-pr-chain, live-github-pr, plugin-set-valid)
├── pr-lifecycle/         5 tests (codeowners-glob, github-urllib, host-detection, pr-description, …)
├── shared/               1 test  (atomic-json)
├── sylph-gate/          3 tests (hook-flow, destructive-op detection, audit)
├── sylph-learning/      3 tests (priors-load, checkpoint, ema-update)
└── run-all.sh            Master runner
```

## Cross-Ecosystem Event Hooks

| Event (consumed) | From | Used by |
|------------------|------|---------|
| `hydra.action.dangerous` | Hydra | sylph-gate (escalates classification) |
| `raven.diff.compressed` | Raven | commit-intelligence (diff > 1500 tokens) |
| `raven.session.continuity` | Raven | pr-lifecycle (context for PR description) |

| Event (published) | Purpose |
|-------------------|---------|
| `sylph.task.boundary.detected` | Signals other plugins that work has naturally completed |
| `sylph.commit.drafted` / `sylph.commit.committed` | Commit lifecycle signals |
| `sylph.pr.drafted` / `sylph.pr.ready` / `sylph.pr.merged` | PR lifecycle signals |
| `sylph.ci.status.observed` | CI observation for downstream consumers |
