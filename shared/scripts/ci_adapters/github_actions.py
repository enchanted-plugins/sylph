"""
GitHub Actions CI adapter.

Reads Check Runs via `gh api repos/{owner}/{repo}/commits/{ref}/check-runs`.
Streams logs via `gh run view --log`. Uses `gh run rerun` for re-triggering.

Stdlib only. `gh` is an optional runtime dep; absent → is_available() is False.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from . import Check, CIAdapter, NotImplementedCIOp
from registry_loader import get_ci_system


class GitHubActionsAdapter(CIAdapter):
    system_id = "github-actions"

    def __init__(self, gh_bin: str = "gh"):
        self.gh = gh_bin
        # Snapshot the CI registry entry. The `gh` CLI provides the real
        # transport here; status_api_path + rerun_api live in the registry
        # as the canonical contract for REST callers that sidestep gh.
        # NOTE: the capability-memory registry keys with dashes
        # ("github-actions"), while ci-registry.json uses underscores
        # ("github_actions"). We key CI by the underscore form per the
        # ci-registry schema.
        self.registry = get_ci_system("github_actions")

    def is_available(self) -> bool:
        if shutil.which(self.gh) is None:
            return False
        try:
            r = subprocess.run(
                [self.gh, "auth", "status"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False
        return r.returncode == 0

    def latest_status(self, repo: str, ref: str) -> list[Check]:
        if not self.is_available():
            return []

        try:
            r = subprocess.run(
                [self.gh, "api", f"repos/{repo}/commits/{ref}/check-runs"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return []

        if r.returncode != 0:
            return []

        try:
            data = json.loads(r.stdout or "{}")
        except json.JSONDecodeError:
            return []

        checks: list[Check] = []
        for cr in data.get("check_runs", []):
            checks.append(Check(
                system=self.system_id,
                name=str(cr.get("name") or ""),
                status=str(cr.get("status") or "queued"),
                conclusion=cr.get("conclusion"),
                url=str(cr.get("html_url") or cr.get("url") or ""),
                started_at=cr.get("started_at"),
                completed_at=cr.get("completed_at"),
                raw=cr,
            ))
        return checks

    def stream_logs(self, check_id: str):
        """Stream logs from a run. GitHub Actions addresses runs, not
        individual check runs, so callers should pass the run id (from
        the raw payload's `check_suite.id` or similar). Yields line strings."""
        if not self.is_available():
            raise NotImplementedCIOp(self.system_id, "stream_logs: gh not available")

        proc = subprocess.Popen(
            [self.gh, "run", "view", str(check_id), "--log"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                yield line.rstrip("\n")
        finally:
            proc.stdout.close()
            proc.wait(timeout=5)

    def rerun(self, check_id: str) -> bool:
        """Rerun a workflow run. Sylph only re-runs existing runs; it never
        triggers a fresh run from scratch."""
        if not self.is_available():
            raise NotImplementedCIOp(self.system_id, "rerun: gh not available")

        try:
            r = subprocess.run(
                [self.gh, "run", "rerun", str(check_id)],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False
        return r.returncode == 0
