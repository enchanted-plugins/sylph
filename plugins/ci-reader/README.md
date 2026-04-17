# ci-reader

**Read-only status + log-stream across 8 CI systems. Weaver reads; Assembler runs.**

Adapter-per-system. Typed status surface:

```python
class CIAdapter:
    def latest_status(self, ref: str) -> list[Check]          # required, 200ms SLA
    def stream_logs(self, check_id: str) -> Iterator[str]      # optional
    def rerun(self, check_id: str) -> None                      # optional
    def webhook_verify(self, payload: bytes, sig: str) -> bool  # required for push-signal
```

**Weaver never triggers a build** — that's Assembler's ownership (enchanted-plugins Phase 3). Boundary enforced via the enchanted-mcp event bus: Weaver publishes `weaver.ci.trigger.requested`, Assembler fulfils.

Supported systems: GitHub Actions, GitLab CI, CircleCI, Jenkins, Buildkite, Drone/Woodpecker, Tekton, ArgoCD/FluxCD. Jenkins adapter has explicit handling for the `UNSTABLE` result edge case that tripped semantic-release in 2021.

## Install

Part of the [Weaver](../..) bundle:

```
/plugin marketplace add enchanted-plugins/weaver
/plugin install full@weaver
```

Standalone: `/plugin install ci-reader@weaver`.

## Components

One Python stdlib module per CI system under `../shared/ci-adapters/`. Hooks attach to `weaver.pr.*` events to poll status and publish observations.

## Cross-plugin

- **Consumes** `assembler.pipeline.status.changed` (authoritative), `assembler.pipeline.required.failed`.
- **Publishes** `weaver.ci.status.observed`.

Full architecture: [../../docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md#layer-9-cicd-status-read--gating).
