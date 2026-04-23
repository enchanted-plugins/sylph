"""
ci-reader orchestrator.

Consumed by the pr-lifecycle state machine and the /sylph:status command.
Detects which CI systems are configured in the current repo, queries them
for the status of a ref, normalizes into `Check` objects, and returns a
summary.

Sylph reads CI; it never triggers builds. Sylph is a git-workflow
plugin; CI execution belongs to your existing CI pipelines
(push-triggered workflows, etc.).

Stdlib only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _local_import():
    """Import our sibling packages when invoked as a script from a hook."""
    sys.path.insert(0, str(Path(__file__).parent))


def status(repo: str, ref: str, cwd: Path) -> dict[str, Any]:
    """Read CI status from every detected system. Returns a summary dict."""
    _local_import()
    from ci_adapters import detect_system, get_adapter, Check

    detected = detect_system(cwd)
    if not detected:
        return {
            "detected_systems": [],
            "checks": [],
            "all_green": None,
            "any_failing": None,
            "gate_verdict": "no-ci-detected",
            "rationale": (
                "No CI configuration detected in the repo "
                "(.github/workflows/, .gitlab-ci.yml, etc.). "
                "PR gating disabled; proceeds based on reviews only."
            ),
        }

    all_checks: list[Check] = []
    per_system_ok: dict[str, bool] = {}
    manual_handoff: list[str] = []

    for system_id in detected:
        try:
            adapter = get_adapter(system_id)
        except KeyError:
            continue

        if not adapter.is_available():
            manual_handoff.append(system_id)
            per_system_ok[system_id] = False
            continue

        checks = adapter.latest_status(repo, ref)
        all_checks.extend(checks)
        per_system_ok[system_id] = bool(checks)

    if not all_checks:
        # No system produced any checks — either nothing's run yet, or no
        # adapter was available.
        return {
            "detected_systems": detected,
            "available_systems": [s for s, ok in per_system_ok.items() if ok],
            "manual_handoff_systems": manual_handoff,
            "checks": [],
            "all_green": None,
            "any_failing": None,
            "gate_verdict": "pending",
            "rationale": (
                "CI configured but no check runs returned yet "
                "(newly pushed ref, or adapters unavailable). "
                f"Manual handoff for: {manual_handoff or 'none'}."
            ),
        }

    all_green = all(c.is_green for c in all_checks if c.is_terminal)
    any_failing = any(
        c.is_terminal and c.conclusion in ("failure", "timed_out", "cancelled")
        for c in all_checks
    )
    pending = [c for c in all_checks if not c.is_terminal]

    if any_failing:
        verdict = "failing"
    elif pending:
        verdict = "pending"
    elif all_green:
        verdict = "green"
    else:
        verdict = "unknown"

    return {
        "detected_systems": detected,
        "available_systems": [s for s, ok in per_system_ok.items() if ok],
        "manual_handoff_systems": manual_handoff,
        "checks": [c.to_dict() for c in all_checks],
        "check_count": len(all_checks),
        "green_count": sum(1 for c in all_checks if c.is_green),
        "pending_count": len(pending),
        "all_green": all_green,
        "any_failing": any_failing,
        "gate_verdict": verdict,
    }


def __main_cli():
    """Usage:
      python ci_reader.py status <owner/repo> <ref> [cwd]
      python ci_reader.py detect-systems [cwd]
    """
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: ci_reader.py (status|detect-systems) ..."}))
        sys.exit(3)

    action = sys.argv[1]
    cwd = Path(sys.argv[-1]) if len(sys.argv) > 2 and Path(sys.argv[-1]).is_dir() else Path.cwd()

    if action == "detect-systems":
        _local_import()
        from ci_adapters import detect_system
        print(json.dumps(detect_system(cwd)))
        sys.exit(0)

    if action == "status":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "usage: status <owner/repo> <ref> [cwd]"}))
            sys.exit(3)
        repo = sys.argv[2]
        ref = sys.argv[3]
        print(json.dumps(status(repo, ref, cwd), indent=2))
        sys.exit(0)

    print(json.dumps({"error": f"unknown action: {action}"}))
    sys.exit(3)


if __name__ == "__main__":
    __main_cli()
