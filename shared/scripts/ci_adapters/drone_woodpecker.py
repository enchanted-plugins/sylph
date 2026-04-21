"""Drone + Woodpecker adapters. Both share the same (mostly) API shape
since Woodpecker is a community fork of Drone.

Endpoint for both: GET /api/repos/{owner}/{repo}/builds

Woodpecker renamed it to `pipelines` in recent versions; we try both
paths. Authentication is Bearer token from the web UI.
"""

from __future__ import annotations

import os
from typing import Any

from . import Check, CIAdapter, NotImplementedCIOp
from ._http import resolve_token, get_json, CIHttpError
from registry_loader import get_ci_system


class _DroneFamilyBase(CIAdapter):
    env_vars = ["DRONE_TOKEN", "WOODPECKER_TOKEN"]
    credential_host_env = "DRONE_SERVER"
    _registry_id = "drone"

    def __init__(self, token: str | None = None, api_base: str | None = None):
        # Both Drone and Woodpecker are self-hosted. Registry carries
        # auth modes + endpoint paths but no base URL (no SaaS).
        self.registry = get_ci_system(self._registry_id)
        self.api_base = (api_base or os.environ.get("DRONE_SERVER") or "").rstrip("/")
        self._token_explicit = token
        self._token_cached: str | None = None
        self._token_probed = False

    def _token(self) -> str | None:
        if self._token_explicit:
            return self._token_explicit
        if not self._token_probed:
            # Fall back to the server host if that's been set.
            host = (
                os.environ.get(self.credential_host_env, "")
                .replace("https://", "").replace("http://", "").split("/")[0]
            )
            self._token_cached = resolve_token(self.env_vars, host or None)
            self._token_probed = True
        return self._token_cached

    def is_available(self) -> bool:
        return bool(self.api_base) and bool(self._token())

    def _endpoints(self) -> list[str]:
        """Both `/builds` (Drone) and `/pipelines` (Woodpecker v2+)."""
        return ["builds", "pipelines"]

    def latest_status(self, repo: str, ref: str) -> list[Check]:
        tok = self._token()
        if not self.is_available() or tok is None:
            return []
        for endpoint in self._endpoints():
            url = f"{self.api_base}/api/repos/{repo}/{endpoint}?branch={ref}"
            try:
                data = get_json(url, token=tok)
                if isinstance(data, list) and data:
                    return [self._to_check(b) for b in data[:5]]
            except CIHttpError:
                continue
        return []

    def _to_check(self, b: dict[str, Any]) -> Check:
        status = str(b.get("status") or "")
        return Check(
            system=self.system_id,
            name=f"#{b.get('number')}" if b.get("number") else "build",
            status=self._map_status(status),
            conclusion=self._map_conclusion(status),
            url=str(b.get("link") or ""),
            started_at=str(b.get("started") or "") or None,
            completed_at=str(b.get("finished") or "") or None,
            raw=b,
        )

    @staticmethod
    def _map_status(s: str) -> str:
        if s in ("pending", "waiting_on_dependencies"):
            return "queued"
        if s == "running":
            return "in_progress"
        return "completed"

    @staticmethod
    def _map_conclusion(s: str) -> str | None:
        if s == "success":
            return "success"
        if s in ("failure", "error"):
            return "failure"
        if s in ("killed", "declined"):
            return "cancelled"
        return None

    def stream_logs(self, check_id: str):
        raise NotImplementedCIOp(self.system_id, "stream_logs: not yet")

    def rerun(self, check_id: str) -> bool:
        return False


class DroneAdapter(_DroneFamilyBase):
    system_id = "drone"
    _registry_id = "drone"


class WoodpeckerAdapter(_DroneFamilyBase):
    system_id = "woodpecker"
    env_vars = ["WOODPECKER_TOKEN", "DRONE_TOKEN"]
    credential_host_env = "WOODPECKER_SERVER"
    _registry_id = "woodpecker"

    def __init__(self, token: str | None = None, api_base: str | None = None):
        super().__init__(
            token=token,
            api_base=api_base or os.environ.get("WOODPECKER_SERVER"),
        )

    def _endpoints(self) -> list[str]:
        # Woodpecker uses /pipelines in v2+; try that first.
        return ["pipelines", "builds"]
