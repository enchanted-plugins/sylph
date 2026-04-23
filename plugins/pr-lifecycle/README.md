# pr-lifecycle

**Idempotent PR state machine + reviewer routing.**

Engine: **W4 — Blame-Weighted Reviewer Ranker.**

State machine: `drafting → ready → reviewing → approved → queued → merged | closed`. Each transition is an idempotent adapter call — safe to re-run after network flake. PR descriptions assembled from Crow V4 session-continuity nodes (what changed / why / how verified / rollback plan). W4 reviewer ranking: weighted sum of `blame_score × recency_decay × path_depth × codeowners_boost × availability`. Blame score from `git log` per-path with 90-day half-life, depth weighting (deeper files prioritized), CODEOWNERS membership boost (1.5×), Crow availability filter. Top-3 cap (avoids Kubernetes-style reviewer storms).

Merge queues: GitHub Merge Queue, GitLab Merge Trains, Bitbucket Cloud poll-and-merge fallback.

## Install

Part of the [Sylph](../..) bundle:

```
/plugin marketplace add enchanted-plugins/sylph
/plugin install full@sylph
```

Standalone: `/plugin install pr-lifecycle@sylph`.

## Components

| Type | Name | Role |
|------|------|------|
| Agent | pr-description-crafter (Opus) | V4 session-context → markdown body |
| Agent | conflict-resolver (Opus) | Three-way merge proposals (never auto-applied) |
| Skill | pr-description-crafter | V4 → markdown |
| Skill | reviewer-router | W4 skill |
| Command | `/sylph pr` | Open / update / promote draft PR |
| Command | `/sylph gate-check` | Explicit merge-queue gate query for a PR head SHA |
| Script | reviewer_route.py | W4 scoring |
| Script | merge_queue_gate.py | CI-status aggregator — allow / block / unknown decision |

## Cross-plugin

- **Consumes** `crow.session.continuity.node` (V4) for PR descriptions, `crow.reviewer.availability.changed` for routing filter.
- **Publishes** `sylph.pr.drafted`, `sylph.pr.ready`, `sylph.pr.merged`.

## Chain-listener (auto-orchestration)

The `PostToolUse(Bash)` hook at [hooks/post-tool-use/on-commit.sh](hooks/post-tool-use/on-commit.sh) closes the auto-orchestration chain:

```
boundary detected → branch-suggested → commit-drafted → commit-committed → PR-drafted
```

It tails `plugins/commit-intelligence/state/executed-commits.jsonl` (appended by `/sylph:commit` on every successful commit) and, for each `sylph.commit.committed` event past the persisted byte offset at `state/listener-offset.json`, appends a draft PR record to `state/pending-prs.jsonl`. The `/sylph:pr` skill consumes that inbox on invocation, composes the full description via `PRDescription.from_cluster` (W2 cluster + V4 continuity), ranks reviewers through W4, and dispatches to the host adapter.

Contract:

- **Advisory-only** — never blocks Bash execution, exits 0 unconditionally.
- **Idempotent** — re-running with no new executed-commit events is a no-op.
- **No network** — the hook only drafts a record; API calls are skill-invoked.
- **Signal** — only records with `event:"sylph.commit.committed"` are honored; other Bash output is ignored.

Option B architecture: one event file per stream. Upstream (`commit-intelligence/state/executed-commits.jsonl`) is the canonical feed; each downstream listener owns its own offset.

## Merge-queue gate

The **draft -> ready-for-review** promotion routes through `shared/scripts/merge_queue_gate.py` before any host mutation. This fulfils the `ci-reader` contract in [CLAUDE.md](../../CLAUDE.md): "gates merge-queue entry" on CI status.

- **Registry-driven.** `plugins/ci-reader/state/ci-registry.json` is the single source of truth for which systems gate — every system with `gate_merge_queue: true` is queried, everything else is skipped. (ArgoCD / WixieCD are read-only: they surface drift, never gate.)
- **Adapter-agnostic.** The gate calls each adapter's existing `latest_status(repo, ref)`; no adapter code was modified. Unavailable adapters (no `gh`, no kubeconfig, etc.) contribute `unknown`, never silent green.
- **Three-valued decision.** `allow` / `block` / `unknown`, with `--strict` promoting `unknown` to `block` when callers want fail-closed semantics.
- **Traffic-light normalization.** Heterogeneous conclusion enums (GitHub `success`/`failure`, GitLab `success`/`failed`, Jenkins `SUCCESS`/`FAILURE`/`UNSTABLE`, Tekton `Succeeded`/`Failed`, etc.) collapse to green/red/yellow/skip via a table documented in [commands/gate-check.md](commands/gate-check.md).
- **Offline test harness.** Set `SYLPH_TEST_CI_STATUS=/path/to/fixture.json` to stand in fake status for every adapter call. Used by [tests/pr-lifecycle/test-merge-queue-gate.sh](../../tests/pr-lifecycle/test-merge-queue-gate.sh) to cover the full matrix without live network.

**Public entry points:**

- `merge_queue_gate.check_gate(pr_record, host_id, ci_systems=None, *, strict=False, repo=None)` — programmatic.
- `pr_lifecycle.promote_to_ready(cwd, ...)` — wraps `check_gate` + the draft->ready flip; red / yellow gate results leave the PR untouched.
- `/sylph:gate-check` — ad-hoc gate query; see [commands/gate-check.md](commands/gate-check.md).

**Boundary.** The gate reads CI status only — never triggers a build. When a gate-block is caused by "no status returned", the recovery path is manual: trigger a build through your existing CI pipelines (push-triggered workflows, etc.) and re-run the gate.

Full architecture: [../../docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md#layer-8-prmr-lifecycle-orchestration-w4).
