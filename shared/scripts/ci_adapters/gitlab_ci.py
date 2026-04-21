"""GitLab CI adapter — reads pipeline status for a ref."""

from __future__ import annotations

import urllib.parse
from typing import Any

from . import Check, CIAdapter, NotImplementedCIOp
from ._http import resolve_token, get_json, CIHttpError
from registry_loader import get_ci_system, get_host


def _credential_host_from(api_base: str, fallback: str) -> str:
    return urllib.parse.urlparse(api_base).hostname or fallback


class GitLabCIAdapter(CIAdapter):
    system_id = "gitlab-ci"

    def __init__(
        self,
        token: str | None = None,
        api_base: str | None = None,
        credential_host: str | None = None,
    ):
        # ci-registry.json carries status_api_path / rerun_api / rate limits,
        # but the base URL proper lives on the host registry (gitlab).
        # The two are kept in sync by design — ci-registry.json's
        # source_of_truth header points at the host adapter.
        self.ci_registry = get_ci_system("gitlab_ci")
        host_reg = get_host("gitlab")
        self.api_base = (api_base or host_reg["api_base"]).rstrip("/")
        self.credential_host = credential_host or _credential_host_from(
            self.api_base, "gitlab.com"
        )
        self._token_explicit = token
        self._token_cached: str | None = None
        self._token_probed = False

    def _token(self) -> str | None:
        if self._token_explicit:
            return self._token_explicit
        if not self._token_probed:
            self._token_cached = resolve_token(
                ["GITLAB_TOKEN", "GL_TOKEN"], self.credential_host
            )
            self._token_probed = True
        return self._token_cached

    def is_available(self) -> bool:
        return bool(self._token())

    def _project_id(self, repo: str) -> str:
        return urllib.parse.quote(repo.strip("/"), safe="")

    def latest_status(self, repo: str, ref: str) -> list[Check]:
        tok = self._token()
        if not tok:
            return []
        pid = self._project_id(repo)
        url = f"{self.api_base}/projects/{pid}/pipelines?ref={urllib.parse.quote(ref)}&per_page=5"
        try:
            pipelines = get_json(url, token=tok)
        except CIHttpError:
            return []
        if not isinstance(pipelines, list) or not pipelines:
            return []

        latest = pipelines[0]
        pid_id = latest.get("id")
        # Fetch jobs in the latest pipeline.
        jobs_url = f"{self.api_base}/projects/{pid}/pipelines/{pid_id}/jobs"
        try:
            jobs = get_json(jobs_url, token=tok)
        except CIHttpError:
            return []
        if not isinstance(jobs, list):
            return []

        out: list[Check] = []
        for j in jobs:
            out.append(Check(
                system=self.system_id,
                name=str(j.get("name") or ""),
                status=self._map_status(str(j.get("status") or "")),
                conclusion=self._map_conclusion(str(j.get("status") or "")),
                url=str(j.get("web_url") or ""),
                started_at=j.get("started_at"),
                completed_at=j.get("finished_at"),
                raw=j,
            ))
        return out

    @staticmethod
    def _map_status(s: str) -> str:
        # GitLab: created/pending/running/success/failed/canceled/skipped/manual/waiting_for_resource
        if s in ("created", "pending", "waiting_for_resource", "manual", "scheduled"):
            return "queued"
        if s == "running":
            return "in_progress"
        return "completed"

    @staticmethod
    def _map_conclusion(s: str) -> str | None:
        if s == "success":
            return "success"
        if s == "failed":
            return "failure"
        if s in ("canceled", "skipped"):
            return "cancelled"
        return None

    def stream_logs(self, check_id: str):
        raise NotImplementedCIOp(self.system_id, "stream_logs: use GitLab API /jobs/{id}/trace in a caller-owned loop")

    def rerun(self, check_id: str) -> bool:
        # POST /jobs/{id}/retry returns the new job; success = HTTP 201.
        tok = self._token()
        if not tok:
            return False
        # Caller needs to pass job ID; we can't infer project from check_id alone.
        return False
