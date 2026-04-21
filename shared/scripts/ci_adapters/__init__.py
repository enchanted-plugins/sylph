"""
Weaver CI-adapter package.

Read-only status + log-stream + rerun across GitHub Actions, GitLab CI,
CircleCI, Jenkins, Buildkite, Drone/Woodpecker, Tekton, ArgoCD/FluxCD.

Weaver reads CI; it never triggers builds. The event-bus surface is:
  - Weaver publishes `weaver.ci.status.observed`

Each adapter implements CIAdapter; unimplemented systems raise
NotImplementedCIOp. GitHub Actions is fully implemented; 7 others stub.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class NotImplementedCIOp(Exception):
    def __init__(self, system_id: str, op: str):
        super().__init__(f"{system_id}: {op} not implemented")
        self.system_id = system_id
        self.op = op


@dataclass
class Check:
    """Normalized CI status for a single check on a ref."""
    system: str               # "github-actions" | "gitlab-ci" | ...
    name: str
    status: str               # "queued" | "in_progress" | "completed"
    conclusion: str | None    # "success" | "failure" | "neutral" | "cancelled" | "timed_out" | "action_required" | None
    url: str
    started_at: str | None = None
    completed_at: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "system": self.system,
            "name": self.name,
            "status": self.status,
            "conclusion": self.conclusion,
            "url": self.url,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    @property
    def is_green(self) -> bool:
        """Gate-ready semantics: completed + conclusion == success."""
        return self.status == "completed" and self.conclusion == "success"

    @property
    def is_terminal(self) -> bool:
        """Finished running (regardless of outcome)."""
        return self.status == "completed"


class CIAdapter(ABC):
    system_id: str = "unknown"

    @abstractmethod
    def is_available(self) -> bool:
        """True if this adapter can make API calls in the current env."""

    @abstractmethod
    def latest_status(self, repo: str, ref: str) -> list[Check]:
        """Return check runs / pipeline status for a ref."""

    @abstractmethod
    def stream_logs(self, check_id: str):
        """Generator yielding log lines. May raise NotImplementedCIOp."""

    @abstractmethod
    def rerun(self, check_id: str) -> bool:
        """Re-trigger a check. Returns True on success. May raise
        NotImplementedCIOp (Weaver re-runs existing runs only; fresh
        builds are out of scope)."""


def detect_system(repo_root) -> list[str]:
    """Detect which CI systems are configured in a repo, best-effort.

    Returns an ordered list of system ids with the most likely first.
    Reads config file presence, not runtime state.
    """
    from pathlib import Path
    r = Path(repo_root)
    found: list[str] = []

    if (r / ".github" / "workflows").is_dir():
        found.append("github-actions")

    if (r / ".gitlab-ci.yml").exists():
        found.append("gitlab-ci")

    if (r / ".circleci" / "config.yml").exists() or (r / ".circleci" / "config.yaml").exists():
        found.append("circleci")

    if (r / "Jenkinsfile").exists() or (r / "jenkinsfile").exists():
        found.append("jenkins")

    if any((r / name).exists() for name in (".buildkite", ".buildkite.yml", ".buildkite.yaml")):
        found.append("buildkite")

    if any((r / name).exists() for name in (".drone.yml", ".drone.yaml")):
        found.append("drone")

    if any((r / name).exists() for name in (".woodpecker", ".woodpecker.yml", ".woodpecker.yaml")):
        found.append("woodpecker")

    # Tekton often lives under deploy/tekton or similar — hard to detect
    # without more context. Caller decides.

    # ArgoCD / FluxCD — look for `argocd` / `fluxcd` directories or known yaml shapes.
    if (r / "argocd").is_dir() or (r / ".argocd").is_dir():
        found.append("argocd")
    if (r / "clusters").is_dir() and (r / "flux-system").is_dir():
        found.append("fluxcd")

    return found


def get_adapter(system_id: str) -> CIAdapter:
    """Factory: return adapter for a system id. Raises KeyError for unknowns.

    All 10 CI systems have real implementations. Availability is gated by
    credentials / tooling (tokens, kubectl context) via is_available().
    """
    if system_id == "github-actions":
        from . import github_actions as _gha
        return _gha.GitHubActionsAdapter()
    if system_id == "gitlab-ci":
        from . import gitlab_ci as _gl
        return _gl.GitLabCIAdapter()
    if system_id == "circleci":
        from . import circleci as _cc
        return _cc.CircleCIAdapter()
    if system_id == "jenkins":
        from . import jenkins as _j
        return _j.JenkinsAdapter()
    if system_id == "buildkite":
        from . import buildkite as _bk
        return _bk.BuildkiteAdapter()
    if system_id == "drone":
        from . import drone_woodpecker as _dw
        return _dw.DroneAdapter()
    if system_id == "woodpecker":
        from . import drone_woodpecker as _dw
        return _dw.WoodpeckerAdapter()
    if system_id == "tekton":
        from . import k8s as _k
        return _k.TektonAdapter()
    if system_id == "argocd":
        from . import k8s as _k
        return _k.ArgoCDAdapter()
    if system_id == "fluxcd":
        from . import k8s as _k
        return _k.FluxCDAdapter()

    raise KeyError(f"unknown CI system: {system_id}")
