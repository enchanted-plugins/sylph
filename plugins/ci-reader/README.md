# ci-reader

**Read-only status + log-stream across 8 CI systems.**

Adapter-per-system. Typed status surface:

```python
class CIAdapter:
    def latest_status(self, ref: str) -> list[Check]          # required, 200ms SLA
    def stream_logs(self, check_id: str) -> Iterator[str]      # optional
    def rerun(self, check_id: str) -> None                      # optional
    def webhook_verify(self, payload: bytes, sig: str) -> bool  # required for push-signal
```

**Sylph never triggers a build.** Sylph is a git-workflow plugin; CI execution belongs to your existing CI pipelines (push-triggered workflows, etc.).

Supported systems: GitHub Actions, GitLab CI, CircleCI, Jenkins, Buildkite, Drone/Woodpecker, Tekton, ArgoCD/WixieCD. Jenkins adapter has explicit handling for the `UNSTABLE` result edge case that tripped semantic-release in 2021.

## Registry

`state/ci-registry.json` is the declarative capability surface for the 10 CI systems Sylph reads. Mirrors the pattern established by `capability-memory/state/capability-registry.json`.

Per-system fields: `id`, `display_name`, `status_api_path`, `log_stream_api`, `rerun_api`, `auth_modes`, `rate_limits`, `webhook_event_taxonomy`, `status_enum`, `conclusion_enum`, `supports_check_runs`, `supports_required_status`, `gate_merge_queue`, `known_quirks`, `support_level`.

Support tiers are honest to the internal audit:

- `first-class`: **github_actions** only — fully wired via `gh` CLI fast-path.
- `best-effort`: gitlab_ci, circleci, jenkins, buildkite, drone, woodpecker, tekton — stub adapters with typed status; degrade to manual handoff if credentials/tooling absent.
- `read-only`: argocd, wixiecd — GitOps drift-detection surface, never gate-ready (`gate_merge_queue: false`).

The `SessionStart` hook (`hooks/session-start/load-ci-registry.sh`) warms the registry and prints `ci-registry: N systems loaded, K first-class` to stderr. Fails open: a missing or invalid registry never blocks the session.

Schema validation: `tests/ci-reader/test-ci-registry-schema.sh`.

## Install

Part of the [Sylph](../..) bundle:

```
/plugin marketplace add enchanted-plugins/sylph
/plugin install full@sylph
```

Standalone: `/plugin install ci-reader@sylph`.

## Components

One Python stdlib module per CI system under `../shared/ci-adapters/`. Hooks attach to `sylph.pr.*` events to poll status and publish observations.

## Cross-plugin

- **Publishes** `sylph.ci.status.observed`.

Full architecture: [../../docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md#layer-9-cicd-status-read--gating).
