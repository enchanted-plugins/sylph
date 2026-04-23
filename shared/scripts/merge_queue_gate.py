"""
Sylph merge-queue gate.

Closes the contract promised in `CLAUDE.md` (row: ci-reader — "gates
merge-queue entry"). When a PR promotes from draft → ready-for-review,
`check_gate(...)` aggregates CI status across the gating-eligible systems
declared in `plugins/ci-reader/state/ci-registry.json` and returns a
three-valued decision: `allow` | `block` | `unknown`.

Boundary contract (CLAUDE.md §"CI/CD boundary"):
  - Sylph READS status; Sylph never triggers a build.
  - If an adapter's own is_available() is False we surface it as
    "unknown"; we do NOT degrade silently to "allow".
  - Read-only CI systems (ArgoCD / WixieCD) have `gate_merge_queue: false`
    in the registry and are skipped here — GitOps surfaces drift, not
    gate-ready status.

Decision logic — see the test fixture for the canonical matrix:

    any red       → block
    any yellow    → block (running)
    all green     → allow
    unknown host  → unknown (allow unless --strict)
    no eligible   → unknown (nothing to gate on)

Test-mode override: when `SYLPH_TEST_CI_STATUS` is set to a path, the
JSON at that path stands in for every adapter's `latest_status()` call.
Shape:

    {
      "<ci-system-id>": [
        {"name": "...", "status": "completed", "conclusion": "success"},
        ...
      ],
      ...
    }

Keys use the adapter's `system_id` (dash-form: "github-actions") so the
fixture mirrors what adapters emit at runtime. Missing entries fall
through to an empty check list (same semantics as an adapter returning
nothing).

Stdlib only.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


# ──────────────────────────────────────────────────────────────────────
# Conclusion normalization
#
# The adapters emit heterogeneous conclusion enums (see `ci-registry.json`:
# GitHub Actions uses "success/failure/neutral/...", GitLab uses
# "success/failed/canceled/...", Jenkins uses "SUCCESS/FAILURE/UNSTABLE/..."
# etc). We collapse every known value into a four-colour traffic light.
#
# Casing is lowered before lookup; unknown values fall back to "yellow"
# (treat as still-running rather than silently passing).
# ──────────────────────────────────────────────────────────────────────

_GREEN = frozenset({
    "success", "passed", "succeeded", "ready",
})
_RED = frozenset({
    "failure", "failed", "failing", "timed_out", "pipelineruntimeout",
    "cancelled", "canceled", "aborted", "killed", "error", "unstable",
    "declined", "reconciliationfailed", "stalled", "degraded",
    "action_required", "blocked", "unauthorized",
})
_SKIP = frozenset({
    "neutral", "skipped", "not_built", "not_run", "stale", "suspended",
    "missing",
})


def _classify(status: str | None, conclusion: str | None) -> str:
    """Return one of: 'green' | 'red' | 'yellow' | 'skip'.

    Terminal status decided by `conclusion`; non-terminal status (queued,
    in_progress, manual, on_hold, etc.) is always 'yellow'.
    """
    status_l = (status or "").lower()
    if status_l and status_l != "completed":
        # Non-terminal: queued / in_progress / running / on_hold / manual
        # all count as yellow — still running from the gate's perspective.
        return "yellow"
    if conclusion is None:
        # Terminal-but-no-conclusion is a degenerate state; treat as
        # yellow so we don't promote to allow on bad data.
        return "yellow"
    c = conclusion.lower()
    if c in _GREEN:
        return "green"
    if c in _RED:
        return "red"
    if c in _SKIP:
        return "skip"
    return "yellow"


# ──────────────────────────────────────────────────────────────────────
# Registry + host mapping
# ──────────────────────────────────────────────────────────────────────

# Maps ci-registry system ids (underscore form) to adapter system_ids
# (dash form, as used at runtime). Keeps the two registries decoupled
# from adapter internals.
_SYSTEM_ID_MAP = {
    "github_actions": "github-actions",
    "gitlab_ci": "gitlab-ci",
    "circleci": "circleci",
    "jenkins": "jenkins",
    "buildkite": "buildkite",
    "drone": "drone",
    "woodpecker": "woodpecker",
    "tekton": "tekton",
    "argocd": "argocd",
    "wixiecd": "wixiecd",
}

# Coarse "which CI does this host typically pair with" hint, derived from
# `webhook_event_taxonomy.ci_event` in capability-registry.json. Used as
# a candidate-narrowing hint when the caller can't pass `ci_systems`
# explicitly — never as a hard gate (a GitHub repo can host GitLab CI
# webhooks etc.).
_CI_EVENT_TO_SYSTEM = {
    "check_run": "github_actions",
    "check_suite": "github_actions",
    "workflow_run": "github_actions",
    "pipeline": "gitlab_ci",
    "repo:commit_status_updated": None,   # Bitbucket Cloud — any CI
    "repo:commit_status": None,           # Bitbucket DC — any CI
    "ms.vss-pipelines.run-state-changed-event": None,  # Azure DevOps
    "commit_status": None,                # Gitea / Forgejo / Codeberg
}


def _eligible_systems(
    registry_systems: dict[str, Any],
    host_id: str | None,
    host_registry_entry: dict[str, Any] | None,
    override: list[str] | None,
) -> list[str]:
    """Pick the registry-underscore ids that should be queried for a host.

    Priority:
      1. explicit `override` (from caller or CLI) — trusted as-is.
      2. every registry system with `gate_merge_queue: true`.

    The per-host `ci_event` is *not* a narrow filter: self-hosted runners,
    mirrored repos, and polyglot pipelines can have any CI paired with any
    host. We log the hint in `reasons` but don't drop systems off it.
    """
    if override:
        return [s for s in override if s in registry_systems]
    return [
        sid for sid, entry in registry_systems.items()
        if isinstance(entry, dict) and entry.get("gate_merge_queue") is True
    ]


# ──────────────────────────────────────────────────────────────────────
# Status retrieval (test-mode + live)
# ──────────────────────────────────────────────────────────────────────


def _load_test_fixture() -> dict[str, list[dict[str, Any]]] | None:
    """If SYLPH_TEST_CI_STATUS is set, return the parsed fixture; else None.

    The env var holds a filesystem path. We deliberately don't support
    inline JSON in the env var — keeps the audit-log of fixture contents
    outside of the process environment.
    """
    path = os.environ.get("SYLPH_TEST_CI_STATUS")
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    # Normalize: each value must be a list of dicts.
    out: dict[str, list[dict[str, Any]]] = {}
    for k, v in data.items():
        if isinstance(v, list):
            out[k] = [c for c in v if isinstance(c, dict)]
    return out


def _collect_statuses_live(
    system_underscore_id: str,
    repo: str,
    ref: str,
) -> tuple[list[dict[str, Any]], str | None]:
    """Call the adapter for a single system. Returns (checks, error).

    `error` is non-None when the adapter couldn't produce data — either
    unknown-in-factory, unavailable, or threw. The caller treats that as
    an "unknown" contribution, not a green.
    """
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from ci_adapters import get_adapter
    except Exception as e:  # noqa: BLE001
        return [], f"ci_adapters import failed: {e}"

    dash_id = _SYSTEM_ID_MAP.get(system_underscore_id, system_underscore_id)
    try:
        adapter = get_adapter(dash_id)
    except KeyError:
        return [], f"no adapter registered for {dash_id}"

    try:
        if not adapter.is_available():
            return [], f"{dash_id} adapter not available"
    except Exception as e:  # noqa: BLE001
        return [], f"{dash_id} availability probe failed: {e}"

    try:
        checks = adapter.latest_status(repo, ref)
    except Exception as e:  # noqa: BLE001
        return [], f"{dash_id} latest_status failed: {e}"

    return [c.to_dict() if hasattr(c, "to_dict") else dict(c) for c in checks], None


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────


def check_gate(
    pr_record: dict[str, Any],
    host_id: str,
    ci_systems: list[str] | None = None,
    *,
    strict: bool = False,
    repo: str | None = None,
) -> dict[str, Any]:
    """Aggregate CI status for a PR and decide merge-queue entry.

    Args:
      pr_record: Minimum shape is `{"head_sha": "<sha>"}`. Extras are
        ignored; anything else is Crow session-continuity / W2 cluster
        metadata the caller may choose to carry.
      host_id: capability-registry id (e.g. "github", "gitlab",
        "sourcehut"). Used for the ci_event hint and to lookup the host
        entry for audit purposes.
      ci_systems: optional whitelist of ci-registry ids (underscore form)
        the caller wants to gate on. Overrides the default "every system
        where gate_merge_queue: true".
      strict: if True, `unknown` becomes `block`. The default leaves
        unknown as unknown so callers can distinguish "network flake"
        from "CI red".
      repo: "owner/name" used by live adapters; required for live mode,
        ignored in test-fixture mode.

    Returns:
      {
        "decision": "allow" | "block" | "unknown",
        "reasons": [...],
        "per_system": { "<dash-id>": {...} }, # audit detail
      }
    """
    # Lazy import of registry_loader to keep this module importable in
    # contexts where the registry path walker hasn't fired yet (e.g. some
    # test harnesses that monkey-patch SYLPH_HOME).
    sys.path.insert(0, str(Path(__file__).parent))

    try:
        from registry_loader import load_ci_registry, get_host, RegistryError
    except Exception as e:  # noqa: BLE001
        return {
            "decision": "unknown",
            "reasons": [f"registry loader import failed: {e}"],
            "per_system": {},
        }

    try:
        registry_systems = load_ci_registry()
    except RegistryError as e:
        return {
            "decision": "unknown",
            "reasons": [f"ci-registry.json unavailable: {e}"],
            "per_system": {},
        }

    host_entry: dict[str, Any] | None = None
    try:
        host_entry = get_host(host_id)
    except KeyError:
        # Unknown host: we can still run the gate against defaults, but
        # record the gap for the audit trail.
        pass
    except RegistryError as e:
        return {
            "decision": "unknown",
            "reasons": [f"no registry entry for host {host_id}: {e}"],
            "per_system": {},
        }

    if host_entry is None:
        return {
            "decision": "unknown",
            "reasons": [f"no registry entry for host {host_id}"],
            "per_system": {},
        }

    eligible = _eligible_systems(registry_systems, host_id, host_entry, ci_systems)
    if not eligible:
        reasons = ["no ci system is gate-eligible for this host"]
        return {
            "decision": "block" if strict else "unknown",
            "reasons": reasons,
            "per_system": {},
        }

    head_sha = pr_record.get("head_sha") or pr_record.get("ref") or ""
    if not head_sha:
        return {
            "decision": "unknown",
            "reasons": ["pr_record missing head_sha"],
            "per_system": {},
        }

    fixture = _load_test_fixture()

    per_system: dict[str, dict[str, Any]] = {}
    saw_red: list[str] = []
    saw_yellow: list[str] = []
    saw_unknown: list[str] = []
    saw_green: list[str] = []

    for sid in eligible:
        dash_id = _SYSTEM_ID_MAP.get(sid, sid)
        display = registry_systems.get(sid, {}).get("display_name", dash_id)

        if fixture is not None:
            checks = fixture.get(dash_id, [])
            err: str | None = None
        else:
            if not repo:
                per_system[dash_id] = {
                    "display_name": display,
                    "error": "live mode requires repo",
                    "checks": [],
                }
                saw_unknown.append(display)
                continue
            checks, err = _collect_statuses_live(sid, repo, head_sha)

        if err is not None:
            per_system[dash_id] = {
                "display_name": display,
                "error": err,
                "checks": [],
            }
            saw_unknown.append(display)
            continue

        # Classify each check and fold into the system-level summary.
        system_colour = "green"  # start optimistic, demote on any red/yellow
        per_checks: list[dict[str, Any]] = []
        sys_had_any_terminal = False
        sys_had_any_non_skip = False
        for c in checks:
            colour = _classify(c.get("status"), c.get("conclusion"))
            per_checks.append({
                "name": c.get("name"),
                "status": c.get("status"),
                "conclusion": c.get("conclusion"),
                "colour": colour,
            })
            if colour == "skip":
                continue
            sys_had_any_non_skip = True
            if colour == "green":
                sys_had_any_terminal = True
            elif colour == "red":
                system_colour = "red"
                sys_had_any_terminal = True
            elif colour == "yellow":
                # any yellow demotes to yellow unless already red
                if system_colour != "red":
                    system_colour = "yellow"

        if not checks or not sys_had_any_non_skip:
            # Adapter returned nothing actionable: unknown, not a free pass.
            per_system[dash_id] = {
                "display_name": display,
                "error": "no check runs returned",
                "checks": per_checks,
            }
            saw_unknown.append(display)
            continue

        per_system[dash_id] = {
            "display_name": display,
            "colour": system_colour,
            "checks": per_checks,
        }
        if system_colour == "red":
            # Identify the first failing check for a human-readable reason.
            failing = next(
                (pc for pc in per_checks if pc["colour"] == "red"), None,
            )
            failed_name = failing["name"] if failing else display
            failed_conclusion = (
                failing["conclusion"] if failing else "unknown"
            )
            saw_red.append(
                f"CI {display}: '{failed_name}' conclusion={failed_conclusion}"
            )
        elif system_colour == "yellow":
            saw_yellow.append(f"CI {display} still running")
        else:
            saw_green.append(display)

    # Aggregate — red dominates yellow dominates unknown dominates green.
    if saw_red:
        return {
            "decision": "block",
            "reasons": saw_red,
            "per_system": per_system,
        }
    if saw_yellow:
        return {
            "decision": "block",
            "reasons": saw_yellow,
            "per_system": per_system,
        }
    if saw_unknown:
        reasons = [f"no status from {name}" for name in saw_unknown]
        return {
            "decision": "block" if strict else "unknown",
            "reasons": reasons,
            "per_system": per_system,
        }
    # All eligible systems reported green (or all-skip).
    return {
        "decision": "allow",
        "reasons": [],
        "per_system": per_system,
    }


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────


def __main_cli():
    """Usage:
      python merge_queue_gate.py --host <host_id> --ref <sha> \
                                 [--repo <owner/name>] [--strict] [--json]
    """
    args = sys.argv[1:]
    host_id = ""
    ref = ""
    repo = ""
    strict = False
    as_json = False
    systems: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--host" and i + 1 < len(args):
            host_id = args[i + 1]; i += 2
        elif a == "--ref" and i + 1 < len(args):
            ref = args[i + 1]; i += 2
        elif a == "--repo" and i + 1 < len(args):
            repo = args[i + 1]; i += 2
        elif a == "--system" and i + 1 < len(args):
            systems.append(args[i + 1]); i += 2
        elif a == "--strict":
            strict = True; i += 1
        elif a == "--json":
            as_json = True; i += 1
        elif a in ("-h", "--help"):
            print(__main_cli.__doc__ or "")
            sys.exit(0)
        else:
            print(json.dumps({"error": f"unknown arg: {a}"}))
            sys.exit(3)

    if not host_id or not ref:
        print(json.dumps({"error": "usage: --host <id> --ref <sha>"}))
        sys.exit(3)

    result = check_gate(
        pr_record={"head_sha": ref},
        host_id=host_id,
        ci_systems=systems or None,
        strict=strict,
        repo=repo or None,
    )

    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"decision: {result['decision']}")
        for r in result.get("reasons", []):
            print(f"  - {r}")

    # Exit codes: 0 allow, 1 block, 2 unknown.
    code = {"allow": 0, "block": 1, "unknown": 2}.get(result["decision"], 3)
    sys.exit(code)


if __name__ == "__main__":
    __main_cli()
