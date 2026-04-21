"""Tekton / ArgoCD / FluxCD adapters — kubectl-backed.

All three run in Kubernetes. Rather than take a Python k8s client as a
dep, we shell out to `kubectl` which is the canonical tool operators
already have configured. If `kubectl` is missing or the user has no
current context, every adapter reports is_available()=False and returns
no checks.

- Tekton: watches PipelineRun CRDs. A PipelineRun's
  .status.conditions[type=Succeeded] reports True/False/Unknown.
- ArgoCD: reads Application CRDs. .status.sync.status + .status.health.status.
- FluxCD: reads Kustomization or HelmRelease CRDs. Same condition pattern.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

from . import Check, CIAdapter, NotImplementedCIOp
from registry_loader import get_ci_system


def _kubectl_available() -> bool:
    return shutil.which("kubectl") is not None


def _kubectl_json(*args: str, timeout: float = 15.0) -> dict[str, Any] | None:
    """Run kubectl with JSON output; return parsed dict or None on error."""
    if not _kubectl_available():
        return None
    try:
        r = subprocess.run(
            ["kubectl", *args, "-o", "json"],
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        return None


class _K8sBase(CIAdapter):
    """Shared is_available + rerun stub."""

    def __init__(self, namespace: str | None = None, kubecontext: str | None = None):
        self.namespace = namespace or os.environ.get("WEAVER_K8S_NAMESPACE") or "default"
        self.kubecontext = kubecontext or os.environ.get("WEAVER_KUBECONTEXT")

    def _ns_flag(self) -> list[str]:
        args = ["-n", self.namespace]
        if self.kubecontext:
            args += ["--context", self.kubecontext]
        return args

    def is_available(self) -> bool:
        if not _kubectl_available():
            return False
        # Confirm there's a current context.
        try:
            r = subprocess.run(
                ["kubectl", "config", "current-context"],
                capture_output=True, text=True, timeout=5,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return False
        return r.returncode == 0 and bool(r.stdout.strip())

    def stream_logs(self, check_id: str):
        raise NotImplementedCIOp(self.system_id, "stream_logs: use `kubectl logs` directly")

    def rerun(self, check_id: str) -> bool:
        return False  # kubectl delete + re-apply is caller territory


class TektonAdapter(_K8sBase):
    system_id = "tekton"

    def __init__(self, namespace: str | None = None, kubecontext: str | None = None):
        super().__init__(namespace=namespace, kubecontext=kubecontext)
        self.registry = get_ci_system("tekton")

    def latest_status(self, repo: str, ref: str) -> list[Check]:
        """Tekton has no built-in repo/ref filter on PipelineRuns; operators
        typically label them with the git ref. We list PipelineRuns in the
        configured namespace and return the top-5 by creation time. Filter by
        ref via the `weaver.ref` label when callers use it."""
        if not self.is_available():
            return []
        args = ["get", "pipelinerun", *self._ns_flag(),
                "--sort-by=.metadata.creationTimestamp"]
        if ref and ref not in ("HEAD", ""):
            args += ["-l", f"weaver.ref={ref}"]
        data = _kubectl_json(*args)
        if not data:
            return []
        items = data.get("items") or []
        out: list[Check] = []
        for pr in items[-5:][::-1]:
            conditions = ((pr.get("status") or {}).get("conditions") or [])
            succ = next((c for c in conditions if c.get("type") == "Succeeded"), {})
            sval = succ.get("status")  # "True" | "False" | "Unknown"
            status = "completed" if sval in ("True", "False") else "in_progress"
            conclusion = None
            if sval == "True":
                conclusion = "success"
            elif sval == "False":
                conclusion = "failure"
            name = (pr.get("metadata") or {}).get("name") or ""
            out.append(Check(
                system=self.system_id,
                name=name,
                status=status,
                conclusion=conclusion,
                url="",
                started_at=(pr.get("status") or {}).get("startTime"),
                completed_at=(pr.get("status") or {}).get("completionTime"),
                raw=pr,
            ))
        return out


class ArgoCDAdapter(_K8sBase):
    """ArgoCD — reports Application sync + health status. Not gate-ready:
    ArgoCD is GitOps, meaning CI is upstream. This adapter surfaces drift
    (out-of-sync / degraded) for visibility."""
    system_id = "argocd"

    def __init__(self, namespace: str | None = None, **kw):
        super().__init__(namespace=namespace or "argocd", **kw)
        self.registry = get_ci_system("argocd")

    def latest_status(self, repo: str, ref: str) -> list[Check]:
        if not self.is_available():
            return []
        data = _kubectl_json("get", "application", *self._ns_flag())
        if not data:
            return []
        items = data.get("items") or []
        out: list[Check] = []
        for app in items:
            name = (app.get("metadata") or {}).get("name") or ""
            src = (app.get("spec") or {}).get("source") or {}
            # Filter by repo if provided (repo here is expected to be the
            # git URL or a substring).
            if repo and repo not in str(src.get("repoURL") or ""):
                continue
            sync = ((app.get("status") or {}).get("sync") or {}).get("status", "Unknown")
            health = ((app.get("status") or {}).get("health") or {}).get("status", "Unknown")

            conclusion = None
            if sync == "Synced" and health == "Healthy":
                conclusion = "success"
            elif sync == "OutOfSync" or health in ("Degraded", "Missing"):
                conclusion = "failure"

            out.append(Check(
                system=self.system_id,
                name=f"{name} ({sync}/{health})",
                status="completed",
                conclusion=conclusion,
                url="",
                started_at=None,
                completed_at=None,
                raw=app,
            ))
        return out


class FluxCDAdapter(_K8sBase):
    """FluxCD — reads Kustomization CRDs from flux-system namespace."""
    system_id = "fluxcd"

    def __init__(self, namespace: str | None = None, **kw):
        super().__init__(namespace=namespace or "flux-system", **kw)
        self.registry = get_ci_system("fluxcd")

    def latest_status(self, repo: str, ref: str) -> list[Check]:
        if not self.is_available():
            return []
        data = _kubectl_json("get", "kustomization", *self._ns_flag())
        if not data:
            return []
        items = data.get("items") or []
        out: list[Check] = []
        for k in items:
            name = (k.get("metadata") or {}).get("name") or ""
            conditions = ((k.get("status") or {}).get("conditions") or [])
            ready = next((c for c in conditions if c.get("type") == "Ready"), {})
            rval = ready.get("status")  # "True" | "False"
            conclusion = None
            if rval == "True":
                conclusion = "success"
            elif rval == "False":
                conclusion = "failure"
            out.append(Check(
                system=self.system_id,
                name=name,
                status="completed",
                conclusion=conclusion,
                url="",
                started_at=None,
                completed_at=None,
                raw=k,
            ))
        return out
