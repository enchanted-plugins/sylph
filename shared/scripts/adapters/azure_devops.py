"""
Azure DevOps (Repos) adapter.

VSTS-era REST API. Scoped by organization → project → repository,
addressed via either repo GUID or name. Pull requests live under:

  POST https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repoId}/pullrequests?api-version=7.1

Auth: Personal Access Token (PAT). Azure accepts Basic auth with empty
username and the PAT as password — we pass a base64-encoded `:<PAT>` in
the Authorization header via the _rest helper's `auth_scheme` knob.

`repo` argument convention for this adapter: "{org}/{project}/{repo}"
(3-slash parts, distinct from 2-part GitHub-style).
"""

from __future__ import annotations

import base64
import urllib.parse
from typing import Any

from . import HostAdapter, NotImplementedHostOp, PullRequest
from ._rest import api_request, resolve_token, RestError


API_VERSION = "7.1-preview.1"


class AzureDevOpsAdapter(HostAdapter):
    host_id = "azure-devops"

    def __init__(
        self,
        token: str | None = None,
        api_base: str = "https://dev.azure.com",
        credential_host: str = "dev.azure.com",
    ):
        self.api_base = api_base.rstrip("/")
        self.credential_host = credential_host
        self._token_explicit = token
        self._token_cached: str | None = None
        self._token_probed = False

    def _token(self) -> str | None:
        if self._token_explicit:
            return self._token_explicit
        if not self._token_probed:
            self._token_cached = resolve_token(
                ["AZURE_DEVOPS_TOKEN", "AZURE_TOKEN", "VSTS_TOKEN"],
                self.credential_host,
            )
            self._token_probed = True
        return self._token_cached

    def is_authenticated(self) -> bool:
        return bool(self._token())

    def _require_token(self, op: str) -> str:
        tok = self._token()
        if not tok:
            raise NotImplementedHostOp(self.host_id, f"{op}: no PAT")
        return tok

    def _parse(self, repo: str) -> tuple[str, str, str]:
        """'{org}/{project}/{repo}' → (org, project, repo_name)."""
        parts = repo.strip("/").split("/")
        if len(parts) != 3:
            raise ValueError(f"expected 'org/project/repo', got: {repo}")
        return parts[0], parts[1], parts[2]

    def _req(self, method: str, path: str, body: Any = None) -> Any:
        tok = self._require_token(f"{method} {path}")
        # Azure expects Basic auth with empty user + PAT as password.
        basic = base64.b64encode(f":{tok}".encode("utf-8")).decode("ascii")
        url = f"{self.api_base}{path}"
        try:
            return api_request(
                method,
                url,
                token=basic,
                auth_scheme="Basic",
                body=body,
            )
        except RestError as e:
            raise RuntimeError(str(e)) from e

    # ── PR ops ─────────────────────────────────────────────────────────

    def _pr_path(self, org: str, project: str, repo: str, number: int | None = None) -> str:
        base = (
            f"/{urllib.parse.quote(org)}/{urllib.parse.quote(project)}"
            f"/_apis/git/repositories/{urllib.parse.quote(repo)}/pullrequests"
        )
        if number is not None:
            base += f"/{number}"
        return f"{base}?api-version={API_VERSION}"

    def open_pr(self, repo, base, head, title, body, draft=True, reviewers=None):
        org, project, rname = self._parse(repo)
        payload: dict[str, Any] = {
            "sourceRefName": f"refs/heads/{head}",
            "targetRefName": f"refs/heads/{base}",
            "title": title,
            "description": body,
            "isDraft": bool(draft),
        }
        if reviewers:
            # Azure DevOps expects id objects. Pass the username as identity;
            # Azure resolves at server side. Unknown users surface a 400.
            payload["reviewers"] = [{"id": u} for u in reviewers]
        created = self._req("POST", self._pr_path(org, project, rname), payload)
        assert isinstance(created, dict)
        return self._pr_to_pr(repo, created)

    def update_pr(self, repo, number, *, title=None, body=None, draft=None, reviewers=None):
        org, project, rname = self._parse(repo)
        patch: dict[str, Any] = {}
        if title is not None:
            patch["title"] = title
        if body is not None:
            patch["description"] = body
        if draft is not None:
            patch["isDraft"] = bool(draft)
        if patch:
            self._req(
                "PATCH",
                self._pr_path(org, project, rname, number),
                patch,
            )
        # Reviewer add is a separate endpoint in ADO.
        if reviewers:
            for user in reviewers:
                try:
                    self._req(
                        "PUT",
                        f"/{org}/{project}/_apis/git/repositories/{rname}"
                        f"/pullRequests/{number}/reviewers/{urllib.parse.quote(user)}"
                        f"?api-version={API_VERSION}",
                        {"vote": 0},
                    )
                except Exception:
                    continue
        return self.get_pr(repo, number)

    def get_pr(self, repo, number):
        org, project, rname = self._parse(repo)
        pr = self._req("GET", self._pr_path(org, project, rname, number))
        assert isinstance(pr, dict)
        return self._pr_to_pr(repo, pr)

    def merge_pr(self, repo, number, strategy="merge-commit"):
        org, project, rname = self._parse(repo)
        # Azure uses "completion options" + status: completed on a PATCH.
        payload = {
            "status": "completed",
            "lastMergeSourceCommit": (
                self._req("GET", self._pr_path(org, project, rname, number))
                .get("lastMergeSourceCommit")
            ),
            "completionOptions": {
                "deleteSourceBranch": True,
                "squashMerge": strategy == "squash",
                "mergeStrategy": {
                    "merge-commit": "noFastForward",
                    "squash": "squash",
                    "rebase": "rebase",
                }.get(strategy, "noFastForward"),
            },
        }
        self._req("PATCH", self._pr_path(org, project, rname, number), payload)
        return self.get_pr(repo, number)

    def close_pr(self, repo, number):
        org, project, rname = self._parse(repo)
        self._req("PATCH", self._pr_path(org, project, rname, number), {"status": "abandoned"})
        return self.get_pr(repo, number)

    def list_checks(self, repo, ref):
        # Azure Pipelines lives on a separate endpoint; ci-reader covers it.
        return []

    def enqueue_merge(self, repo, number):
        # Azure has no merge queue / auto-merge.
        return False

    def _pr_to_pr(self, repo: str, pr: dict[str, Any]) -> PullRequest:
        raw_status = str(pr.get("status") or "").lower()  # active|completed|abandoned
        is_draft = bool(pr.get("isDraft"))
        if raw_status == "completed":
            state = "merged"
        elif raw_status == "abandoned":
            state = "closed"
        elif is_draft:
            state = "draft"
        else:
            state = "open"

        org, project, rname = self._parse(repo)
        number = int(pr.get("pullRequestId") or 0)
        url = (
            f"{self.api_base}/{org}/{project}/_git/{rname}/pullrequest/{number}"
        )
        source = str(pr.get("sourceRefName") or "").replace("refs/heads/", "")
        target = str(pr.get("targetRefName") or "").replace("refs/heads/", "")
        reviewers = [
            r.get("displayName") or r.get("uniqueName") or ""
            for r in (pr.get("reviewers") or [])
        ]

        return PullRequest(
            host=self.host_id,
            repo=repo,
            number=number,
            url=url,
            state=state,
            title=str(pr.get("title") or ""),
            body=str(pr.get("description") or ""),
            base=target,
            head=source,
            reviewers=reviewers,
        )
