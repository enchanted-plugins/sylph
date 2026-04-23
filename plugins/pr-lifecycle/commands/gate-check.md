---
name: sylph:gate-check
description: Explicit merge-queue gate query. Reads CI status across every gate-eligible system in ci-registry.json and returns allow/block/unknown for a given PR head SHA. Offline read — never mutates the PR and never triggers a build.
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/merge_queue_gate.py *), Bash(python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/merge_queue_gate.py *), Bash(git rev-parse *), Bash(git remote get-url *), Read(plugins/ci-reader/state/ci-registry.json)
---

# /sylph:gate-check

Ask the merge-queue gate whether a PR is ready to enter the queue. This is the same gate that `/sylph:pr --ready` runs automatically; expose it standalone for ad-hoc queries and CI debugging.

## Usage

```
/sylph:gate-check                                # gate current HEAD on detected host
/sylph:gate-check --ref <sha>                    # gate an explicit commit
/sylph:gate-check --host <host_id>               # explicit host (defaults to origin's)
/sylph:gate-check --repo <owner/name>            # explicit repo for live adapters
/sylph:gate-check --system github_actions        # restrict to one CI system
/sylph:gate-check --strict                       # unknown counts as block
/sylph:gate-check --json                         # machine-readable output
```

## What it does

1. Loads `plugins/ci-reader/state/ci-registry.json`. Picks every system where `gate_merge_queue: true` (ArgoCD / WixieCD / Jenkins / Buildkite / CircleCI / Drone / Woodpecker / Tekton are all `false` — GitOps and best-effort CI don't gate).
2. For each eligible system, queries the adapter's `latest_status(repo, ref)`. Unavailable adapters (no `gh` CLI, no kubeconfig, etc.) are recorded as `unknown` — never silently treated as green.
3. Normalizes each check's `conclusion` through the traffic-light table:

   | colour   | conclusions                                                                                     |
   |----------|--------------------------------------------------------------------------------------------------|
   | green    | `success` / `passed` / `succeeded` / `Ready`                                                     |
   | red      | `failure` / `failed` / `timed_out` / `cancelled` / `aborted` / `unstable` / `error` / `blocked`  |
   | yellow   | non-terminal status (queued / in_progress / running / manual / on_hold)                          |
   | skip     | `neutral` / `skipped` / `not_run` / `stale` / `suspended`                                        |

4. Aggregates: any red -> **block**, any yellow -> **block (still running)**, all green -> **allow**, nothing to decide on -> **unknown** (or **block** under `--strict`).

## Output

Human-readable by default:

```
decision: block
  - CI GitHub Actions: 'test-integration' conclusion=failure
```

`--json` emits the full decision record:

```
{
  "decision": "block",
  "reasons": ["CI GitHub Actions: 'test-integration' conclusion=failure"],
  "per_system": {
    "github-actions": {
      "display_name": "GitHub Actions",
      "colour": "red",
      "checks": [
        {"name": "build", "status": "completed", "conclusion": "success", "colour": "green"},
        {"name": "test-integration", "status": "completed", "conclusion": "failure", "colour": "red"}
      ]
    }
  }
}
```

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | `allow` — merge queue entry permitted |
| 1 | `block` — at least one required check is red or running |
| 2 | `unknown` — nothing queryable; `--strict` promotes this to block |
| 3 | argument error |

## Boundary notes

- **Read-only.** This command never mutates the PR, never triggers a build, and never advances state. That belongs to `/sylph:pr --ready`, which routes through the same gate before flipping draft->ready.
- **Offline fixture mode.** Set `SYLPH_TEST_CI_STATUS=/path/to/fixture.json` to stand in fake CI status — used by the `tests/pr-lifecycle/test-merge-queue-gate.sh` fixtures. Production leaves this unset.
