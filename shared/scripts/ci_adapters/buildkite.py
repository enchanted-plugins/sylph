"""Buildkite adapter — reads builds via REST API."""

from __future__ import annotations

import urllib.parse
from typing import Any

from . import Check, CIAdapter, NotImplementedCIOp
from ._http import resolve_token, get_json, CIHttpError
from registry_loader import get_ci_system


# Like CircleCI, ci-registry carries the path template (not the base);
# we hold the documented Buildkite SaaS base here, sourced from the
# registry when that field is added to the schema.
_BUILDKITE_DEFAULT_BASE = "https://api.buildkite.com/v2"


class BuildkiteAdapter(CIAdapter):
    system_id = "buildkite"

    def __init__(self, token: str | None = None, api_base: str | None = None):
        self.registry = get_ci_system("buildkite")
        reg_base = self.registry.get("api_base") or _BUILDKITE_DEFAULT_BASE
        self.api_base = (api_base or reg_base).rstrip("/")
        self._token_explicit = token
        self._token_cached: str | None = None
        self._token_probed = False

    def _token(self) -> str | None:
        if self._token_explicit:
            return self._token_explicit
        if not self._token_probed:
            self._token_cached = resolve_token(
                ["BUILDKITE_TOKEN", "BUILDKITE_API_TOKEN"], "buildkite.com"
            )
            self._token_probed = True
        return self._token_cached

    def is_available(self) -> bool:
        return bool(self._token())

    def latest_status(self, repo: str, ref: str) -> list[Check]:
        """`repo` for Buildkite = '{org}/{pipeline-slug}'."""
        tok = self._token()
        if not tok:
            return []
        if "/" not in repo:
            return []
        org, pipeline = repo.split("/", 1)
        url = (
            f"{self.api_base}/organizations/{urllib.parse.quote(org)}"
            f"/pipelines/{urllib.parse.quote(pipeline)}"
            f"/builds?branch={urllib.parse.quote(ref)}&per_page=5"
        )
        try:
            builds = get_json(url, token=tok)
        except CIHttpError:
            return []
        if not isinstance(builds, list) or not builds:
            return []

        out: list[Check] = []
        for b in builds:
            out.append(Check(
                system=self.system_id,
                name=f"Build #{b.get('number')}",
                status=self._map_status(str(b.get("state") or "")),
                conclusion=self._map_conclusion(str(b.get("state") or "")),
                url=str(b.get("web_url") or ""),
                started_at=b.get("started_at"),
                completed_at=b.get("finished_at"),
                raw=b,
            ))
        return out

    @staticmethod
    def _map_status(s: str) -> str:
        if s in ("scheduled", "creating"):
            return "queued"
        if s in ("running", "canceling"):
            return "in_progress"
        return "completed"

    @staticmethod
    def _map_conclusion(s: str) -> str | None:
        if s == "passed":
            return "success"
        if s in ("failed", "blocked"):
            return "failure"
        if s in ("canceled", "skipped"):
            return "cancelled"
        return None

    def stream_logs(self, check_id: str):
        raise NotImplementedCIOp(self.system_id, "stream_logs: use /builds/{id}/jobs/{job}/log")

    def rerun(self, check_id: str) -> bool:
        return False
