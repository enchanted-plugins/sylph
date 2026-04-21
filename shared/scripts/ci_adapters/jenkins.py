"""Jenkins adapter — reads BuildData for a job/build, handles UNSTABLE correctly."""

from __future__ import annotations

import urllib.parse
from typing import Any

from . import Check, CIAdapter, NotImplementedCIOp
from ._http import resolve_token, get_json, CIHttpError
from registry_loader import get_ci_system


class JenkinsAdapter(CIAdapter):
    system_id = "jenkins"

    def __init__(
        self,
        token: str | None = None,
        api_base: str | None = None,
        username: str | None = None,
        credential_host: str | None = None,
    ):
        import os
        # Jenkins is always self-hosted — ci-registry carries path + auth
        # modes but no base URL (there's no SaaS). JENKINS_URL env remains
        # the runtime source of truth; registry supplies the contract.
        self.registry = get_ci_system("jenkins")
        self.api_base = (api_base or os.environ.get("JENKINS_URL") or "").rstrip("/")
        self.username = username or os.environ.get("JENKINS_USER")
        self.credential_host = credential_host
        self._token_explicit = token
        self._token_cached: str | None = None
        self._token_probed = False

    def _token(self) -> str | None:
        if self._token_explicit:
            return self._token_explicit
        if not self._token_probed:
            self._token_cached = resolve_token(
                ["JENKINS_TOKEN", "JENKINS_API_TOKEN"],
                self.credential_host,
            )
            self._token_probed = True
        return self._token_cached

    def is_available(self) -> bool:
        return bool(self.api_base) and bool(self._token())

    def latest_status(self, repo: str, ref: str) -> list[Check]:
        """For Jenkins, `repo` is the job path (e.g., 'myjob' or 'folder/job/sub').
        `ref` is ignored — Jenkins resolves latest-build implicitly via lastBuild."""
        if not self.is_available():
            return []
        tok = self._token()
        # Basic auth: user:token, base64. CIHttpError via BasicAuth isn't exposed
        # in get_json so we inline the urllib path here.
        import base64, urllib.request, json as _json
        creds = base64.b64encode(f"{self.username or 'weaver'}:{tok}".encode()).decode()
        url = f"{self.api_base}/job/{urllib.parse.quote(repo, safe='/')}/lastBuild/api/json"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Basic {creds}",
            "Accept": "application/json",
            "User-Agent": "weaver/0.1.0",
        })
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = _json.loads(resp.read().decode())
        except Exception:
            return []

        # Jenkins "result": SUCCESS | FAILURE | UNSTABLE | ABORTED | null (still building)
        result = data.get("result")
        building = bool(data.get("building"))

        status = "in_progress" if building else "completed"
        # CRITICAL: per the Jenkins-vs-semantic-release incident, UNSTABLE is NOT success.
        if result == "SUCCESS":
            conclusion = "success"
        elif result in ("FAILURE", "UNSTABLE"):
            conclusion = "failure"
        elif result == "ABORTED":
            conclusion = "cancelled"
        else:
            conclusion = None

        return [Check(
            system=self.system_id,
            name=str(data.get("fullDisplayName") or repo),
            status=status,
            conclusion=conclusion,
            url=str(data.get("url") or ""),
            started_at=None,
            completed_at=None,
            raw=data,
        )]

    def stream_logs(self, check_id: str):
        raise NotImplementedCIOp(self.system_id, "stream_logs: use /consoleText directly")

    def rerun(self, check_id: str) -> bool:
        return False  # Jenkins rebuild needs CSRF crumb; out of scope.
