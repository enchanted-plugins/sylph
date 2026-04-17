# pr-lifecycle

**Idempotent PR state machine + reviewer routing.**

Engine: **W4 — Path-History Reviewer Routing.**

State machine: `drafting → ready → reviewing → approved → queued → merged | closed`. Each transition is an idempotent adapter call — safe to re-run after network flake. PR descriptions assembled from Hornet V4 session-continuity nodes (what changed / why / how verified / rollback plan). W4 reviewer ranking: `git log` blame-graph weighted by recency (90-day half-life) and path-depth, unioned with CODEOWNERS, filtered by Hornet availability events, capped at 3 (avoids Kubernetes-style reviewer storms).

Merge queues: GitHub Merge Queue, GitLab Merge Trains, Bitbucket Cloud poll-and-merge fallback.

## Install

Part of the [Weaver](../..) bundle:

```
/plugin marketplace add enchanted-plugins/weaver
/plugin install full@weaver
```

Standalone: `/plugin install pr-lifecycle@weaver`.

## Components

| Type | Name | Role |
|------|------|------|
| Agent | pr-description-crafter (Opus) | V4 session-context → markdown body |
| Agent | conflict-resolver (Opus) | Three-way merge proposals (never auto-applied) |
| Skill | pr-description-crafter | V4 → markdown |
| Skill | reviewer-router | W4 skill |
| Command | `/weaver pr` | Open / update / promote draft PR |
| Script | reviewer_route.py | W4 scoring |

## Cross-plugin

- **Consumes** `hornet.session.continuity.node` (V4) for PR descriptions, `hornet.reviewer.availability.changed` for routing filter, `assembler.pipeline.status.changed` for state transitions.
- **Publishes** `weaver.pr.drafted`, `weaver.pr.ready`, `weaver.pr.merged`.

Full architecture: [../../docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md#layer-8-prmr-lifecycle-orchestration-w4).
