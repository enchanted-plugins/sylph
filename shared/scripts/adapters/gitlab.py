"""
GitLab adapter (SaaS + self-managed).

GitLab Merge Requests via REST v4. Project identifier uses URL-encoded
full path — e.g., `enchanted-plugins/weaver` becomes `enchanted-plugins%2Fweaver`.

Token resolution: $GITLAB_TOKEN, $GL_TOKEN, or git-credential fill for
`gitlab.com` (SaaS) / self-managed host.

Merge queue equivalent: "Merge Trains" — enabled via merge_when_pipeline_succeeds
flag on the merge call.

Stdlib only.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

from . import HostAdapter, NotImplementedHostOp, PullRequest
from ._rest import api_request, resolve_token, RestError


class GitLabAdapter(HostAdapter):
    host_id = "gitlab"

    def __init__(
        self,
        token: str | None = None,
        api_base: str = "https://gitlab.com/api/v4",
        credential_host: str = "gitlab.com",
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
                ["GITLAB_TOKEN", "GL_TOKEN"], self.credential_host
            )
            self._token_probed = True
        return self._token_cached

    def is_authenticated(self) -> bool:
        return bool(self._token())

    def _require_token(self, op: str) -> str:
        tok = self._token()
        if not tok:
            raise NotImplementedHostOp(
                self.host_id,
                f"{op}: no token (set GITLAB_TOKEN or configure git credential-manager for {self.credential_host})",
            )
        return tok

    def _project_id(self, repo: str) -> str:
        """URL-encode the full project path for GitLab API."""
        return urllib.parse.quote(repo.strip("/"), safe="")

    # ── PR ops ──────────────────────────────────────────────────────────

    def open_pr(
        self,
        repo: str,
        base: str,
        head: str,
        title: str,
        body: str,
        draft: bool = True,
        reviewers: list[str] | None = None,
    ) -> PullRequest:
        tok = self._require_token("open_pr")
        pid = self._project_id(repo)
        url = f"{self.api_base}/projects/{pid}/merge_requests"
        payload: dict[str, Any] = {
            "source_branch": head,
            "target_branch": base,
            "title": f"Draft: {title}" if draft else title,
            "description": body,
        }
        if reviewers:
            # GitLab needs numeric user IDs for reviewers; resolve from usernames.
            ids = self._resolve_user_ids(tok, reviewers)
            if ids:
                payload["reviewer_ids"] = ids

        try:
            created = api_request("POST", url, token=tok, body=payload)
        except RestError as e:
            raise RuntimeError(str(e)) from e

        assert isinstance(created, dict)
        return self._mr_to_pr(repo, created)

    def _resolve_user_ids(self, tok: str, usernames: list[str]) -> list[int]:
        """GitLab wants numeric user IDs for reviewer assignment."""
        ids: list[int] = []
        for username in usernames:
            try:
                users = api_request(
                    "GET",
                    f"{self.api_base}/users?username={urllib.parse.quote(username)}",
                    token=tok,
                )
                if isinstance(users, list) and users:
                    ids.append(int(users[0]["id"]))
            except Exception:
                # Unknown user / forbidden — skip silently.
                continue
        return ids

    def update_pr(
        self,
        repo: str,
        number: int,
        *,
        title: str | None = None,
        body: str | None = None,
        draft: bool | None = None,
        reviewers: list[str] | None = None,
    ) -> PullRequest:
        tok = self._require_token("update_pr")
        pid = self._project_id(repo)
        url = f"{self.api_base}/projects/{pid}/merge_requests/{number}"
        patch: dict[str, Any] = {}
        if title is not None:
            patch["title"] = title
        if body is not None:
            patch["description"] = body
        if draft is True:
            patch["title"] = f"Draft: {title or self.get_pr(repo, number).title}"
        elif draft is False:
            # Drop the "Draft:" prefix if present
            current = title or self.get_pr(repo, number).title
            patch["title"] = current.removeprefix("Draft: ").removeprefix("WIP: ")
        if reviewers:
            ids = self._resolve_user_ids(tok, reviewers)
            if ids:
                patch["reviewer_ids"] = ids
        if patch:
            try:
                api_request("PUT", url, token=tok, body=patch)
            except RestError as e:
                raise RuntimeError(str(e)) from e
        return self.get_pr(repo, number)

    def get_pr(self, repo: str, number: int) -> PullRequest:
        tok = self._require_token("get_pr")
        pid = self._project_id(repo)
        url = f"{self.api_base}/projects/{pid}/merge_requests/{number}"
        try:
            mr = api_request("GET", url, token=tok)
        except RestError as e:
            raise RuntimeError(str(e)) from e
        assert isinstance(mr, dict)
        return self._mr_to_pr(repo, mr)

    def merge_pr(self, repo: str, number: int, strategy: str = "merge-commit") -> PullRequest:
        tok = self._require_token("merge_pr")
        pid = self._project_id(repo)
        url = f"{self.api_base}/projects/{pid}/merge_requests/{number}/merge"
        payload: dict[str, Any] = {}
        if strategy == "squash":
            payload["squash"] = True
        # GitLab's "rebase-commit" is driven by the project setting, not the call.
        try:
            api_request("PUT", url, token=tok, body=payload)
        except RestError as e:
            raise RuntimeError(str(e)) from e
        return self.get_pr(repo, number)

    def enqueue_merge(self, repo: str, number: int) -> bool:
        """Merge Trains: set merge_when_pipeline_succeeds=true."""
        tok = self._require_token("enqueue_merge")
        pid = self._project_id(repo)
        url = f"{self.api_base}/projects/{pid}/merge_requests/{number}/merge"
        try:
            api_request("PUT", url, token=tok, body={"merge_when_pipeline_succeeds": True})
            return True
        except RestError:
            return False

    def close_pr(self, repo: str, number: int) -> PullRequest:
        tok = self._require_token("close_pr")
        pid = self._project_id(repo)
        url = f"{self.api_base}/projects/{pid}/merge_requests/{number}"
        try:
            api_request("PUT", url, token=tok, body={"state_event": "close"})
        except RestError as e:
            raise RuntimeError(str(e)) from e
        return self.get_pr(repo, number)

    def list_checks(self, repo: str, ref: str) -> list[dict[str, Any]]:
        tok = self._require_token("list_checks")
        pid = self._project_id(repo)
        # GitLab pipelines are the CI equivalent; refer by ref (branch or sha).
        url = f"{self.api_base}/projects/{pid}/pipelines?ref={urllib.parse.quote(ref)}"
        try:
            pipelines = api_request("GET", url, token=tok)
        except RestError as e:
            raise RuntimeError(str(e)) from e
        if not isinstance(pipelines, list):
            return []
        # Return the most recent pipeline's jobs; caller ci-reader does its own
        # normalization to Check objects.
        return pipelines[:20]

    # ── helpers ────────────────────────────────────────────────────────

    def _mr_to_pr(self, repo: str, mr: dict[str, Any]) -> PullRequest:
        """Normalize a GitLab MR payload into Weaver's PullRequest shape."""
        raw_state = str(mr.get("state") or "").lower()
        draft = bool(mr.get("draft") or mr.get("work_in_progress"))
        if raw_state == "merged":
            state = "merged"
        elif raw_state == "closed":
            state = "closed"
        elif draft:
            state = "draft"
        else:
            state = "open"

        reviewers = [
            r.get("username") for r in (mr.get("reviewers") or []) if r.get("username")
        ]

        return PullRequest(
            host=self.host_id,
            repo=repo,
            number=int(mr.get("iid") or 0),
            url=str(mr.get("web_url") or ""),
            state=state,
            title=str(mr.get("title") or ""),
            body=str(mr.get("description") or ""),
            base=str(mr.get("target_branch") or ""),
            head=str(mr.get("source_branch") or ""),
            reviewers=reviewers,
        )
