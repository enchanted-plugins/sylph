"""
Bitbucket adapters — Cloud (REST 2.0) and Data Center (REST 1.0).

Different APIs, different URL shapes, different PR payload schemas.
They share nothing but the product name.

**Bitbucket Cloud** (bitbucket.org):
  - Repo-scoped: /2.0/repositories/{workspace}/{repo_slug}
  - Auth: App Passwords (deprecating), OAuth, Repository Access Tokens
  - Tokens sent as Bearer. App Passwords use Basic {user}:{app-password}
    but we accept either via the REST helper's auth_scheme knob.
  - PRs live at /pullrequests
  - No merge queue.

**Bitbucket Data Center** (self-hosted Atlassian, formerly Bitbucket Server):
  - Project+repo scoped: /rest/api/1.0/projects/{key}/repos/{slug}
  - Auth: HTTP Personal Access Tokens (Bearer), basic auth, or OAuth
  - PRs live at /pull-requests (hyphenated)
  - No merge queue (same as Cloud).
"""

from __future__ import annotations

import urllib.parse
from typing import Any

from . import HostAdapter, NotImplementedHostOp, PullRequest
from ._rest import api_request, resolve_token, RestError
from registry_loader import get_host


def _credential_host_from(api_base: str, fallback: str) -> str:
    """Derive the git-credential host from a registry api_base URL."""
    return urllib.parse.urlparse(api_base).hostname or fallback


# ──────────────────────────────────────────────────────────────────────
# Bitbucket Cloud
# ──────────────────────────────────────────────────────────────────────


class BitbucketCloudAdapter(HostAdapter):
    host_id = "bitbucket-cloud"

    def __init__(
        self,
        token: str | None = None,
        api_base: str | None = None,
        credential_host: str | None = None,
    ):
        reg = get_host("bitbucket-cloud")
        self.api_base = (api_base or reg["api_base"]).rstrip("/")
        # bitbucket.org is the canonical credential host for SaaS Bitbucket.
        self.credential_host = credential_host or _credential_host_from(
            self.api_base, "bitbucket.org"
        )
        self._token_explicit = token
        self._token_cached: str | None = None
        self._token_probed = False

    def _token(self) -> str | None:
        if self._token_explicit:
            return self._token_explicit
        if not self._token_probed:
            self._token_cached = resolve_token(
                ["BITBUCKET_TOKEN", "BB_TOKEN"], self.credential_host
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
                f"{op}: no token (set BITBUCKET_TOKEN or configure credential-manager)",
            )
        return tok

    def _parse(self, repo: str) -> tuple[str, str]:
        """owner/slug → (workspace, repo_slug)."""
        if "/" not in repo:
            raise ValueError(f"expected owner/repo, got: {repo}")
        ws, slug = repo.split("/", 1)
        return urllib.parse.quote(ws, safe=""), urllib.parse.quote(slug, safe="")

    def _req(self, method: str, path: str, body: Any = None) -> Any:
        tok = self._require_token(f"{method} {path}")
        url = f"{self.api_base}{path}"
        try:
            return api_request(method, url, token=tok, body=body)
        except RestError as e:
            raise RuntimeError(str(e)) from e

    # ── PR ops ─────────────────────────────────────────────────────────

    def open_pr(self, repo, base, head, title, body, draft=True, reviewers=None):
        ws, slug = self._parse(repo)
        payload: dict[str, Any] = {
            "title": f"Draft: {title}" if draft else title,
            "description": body,
            "source": {"branch": {"name": head}},
            "destination": {"branch": {"name": base}},
        }
        if reviewers:
            # Bitbucket wants uuid or username in a nested shape.
            payload["reviewers"] = [{"username": u} for u in reviewers]

        created = self._req("POST", f"/repositories/{ws}/{slug}/pullrequests", payload)
        assert isinstance(created, dict)
        return self._pr_to_pr(repo, created)

    def update_pr(self, repo, number, *, title=None, body=None, draft=None, reviewers=None):
        ws, slug = self._parse(repo)
        patch: dict[str, Any] = {}
        if title is not None:
            patch["title"] = f"Draft: {title}" if draft is True else title
        if body is not None:
            patch["description"] = body
        if draft is False and title is None:
            current = self.get_pr(repo, number).title
            patch["title"] = current.removeprefix("Draft: ").removeprefix("WIP: ")
        if reviewers:
            patch["reviewers"] = [{"username": u} for u in reviewers]
        if patch:
            self._req("PUT", f"/repositories/{ws}/{slug}/pullrequests/{number}", patch)
        return self.get_pr(repo, number)

    def get_pr(self, repo, number):
        ws, slug = self._parse(repo)
        pr = self._req("GET", f"/repositories/{ws}/{slug}/pullrequests/{number}")
        assert isinstance(pr, dict)
        return self._pr_to_pr(repo, pr)

    def merge_pr(self, repo, number, strategy="merge-commit"):
        ws, slug = self._parse(repo)
        style_map = {"merge-commit": "merge_commit", "squash": "squash", "fast-forward": "fast_forward"}
        style = style_map.get(strategy, "merge_commit")
        self._req(
            "POST",
            f"/repositories/{ws}/{slug}/pullrequests/{number}/merge",
            {"merge_strategy": style},
        )
        return self.get_pr(repo, number)

    def close_pr(self, repo, number):
        ws, slug = self._parse(repo)
        self._req("POST", f"/repositories/{ws}/{slug}/pullrequests/{number}/decline")
        return self.get_pr(repo, number)

    def list_checks(self, repo, ref):
        ws, slug = self._parse(repo)
        try:
            data = self._req("GET", f"/repositories/{ws}/{slug}/commit/{ref}/statuses")
            return data.get("values", []) if isinstance(data, dict) else []
        except Exception:
            return []

    def enqueue_merge(self, repo, number):
        # Bitbucket Cloud has no merge queue.
        return False

    # ── helpers ────────────────────────────────────────────────────────

    def _pr_to_pr(self, repo: str, pr: dict[str, Any]) -> PullRequest:
        raw_state = str(pr.get("state") or "").upper()  # "OPEN"|"MERGED"|"DECLINED"|"SUPERSEDED"
        title = str(pr.get("title") or "")
        draft = title.lower().startswith(("draft:", "wip:"))
        if raw_state == "MERGED":
            state = "merged"
        elif raw_state in ("DECLINED", "SUPERSEDED"):
            state = "closed"
        elif draft:
            state = "draft"
        else:
            state = "open"

        return PullRequest(
            host=self.host_id,
            repo=repo,
            number=int(pr.get("id") or 0),
            url=str(((pr.get("links") or {}).get("html") or {}).get("href") or ""),
            state=state,
            title=title,
            body=str(pr.get("description") or ""),
            base=str(((pr.get("destination") or {}).get("branch") or {}).get("name") or ""),
            head=str(((pr.get("source") or {}).get("branch") or {}).get("name") or ""),
            reviewers=[
                (r.get("display_name") or r.get("nickname") or "")
                for r in (pr.get("reviewers") or [])
            ],
        )


# ──────────────────────────────────────────────────────────────────────
# Bitbucket Data Center (ex Server)
# ──────────────────────────────────────────────────────────────────────


class BitbucketDataCenterAdapter(HostAdapter):
    host_id = "bitbucket-dc"

    def __init__(
        self,
        token: str | None = None,
        api_base: str | None = None,
        credential_host: str | None = None,
    ):
        # DC is always self-hosted — the registry carries a placeholder
        # api_base (`https://<self-hosted>/...`) so we consult the registry
        # only to surface documented defaults; callers must supply a real
        # base via env/kwarg. If the registry placeholder leaks through,
        # downstream code already treats an empty/placeholder base as
        # unconfigured via is_authenticated.
        reg = get_host("bitbucket-dc")
        reg_base = reg.get("api_base", "")
        # Treat the "<...>" placeholder as empty; real bases come from
        # caller or env.
        if reg_base and "<" in reg_base:
            reg_base = ""
        self.api_base = (api_base or reg_base).rstrip("/")
        self.credential_host = credential_host or ""
        self._token_explicit = token
        self._token_cached: str | None = None
        self._token_probed = False

    def _token(self) -> str | None:
        if self._token_explicit:
            return self._token_explicit
        if not self._token_probed:
            self._token_cached = resolve_token(
                ["BITBUCKET_DC_TOKEN", "BITBUCKET_TOKEN"], self.credential_host or "bitbucket.example.com"
            )
            self._token_probed = True
        return self._token_cached

    def is_authenticated(self) -> bool:
        return bool(self.api_base) and bool(self._token())

    def _require_auth(self, op: str) -> str:
        if not self.api_base:
            raise NotImplementedHostOp(
                self.host_id, f"{op}: no api_base configured"
            )
        tok = self._token()
        if not tok:
            raise NotImplementedHostOp(
                self.host_id, f"{op}: no token"
            )
        return tok

    def _parse(self, repo: str) -> tuple[str, str]:
        """'PROJECT/repo' → (project_key, repo_slug)."""
        if "/" not in repo:
            raise ValueError(f"expected PROJECT/repo, got: {repo}")
        proj, slug = repo.split("/", 1)
        return proj, slug

    def _req(self, method: str, path: str, body: Any = None) -> Any:
        tok = self._require_auth(f"{method} {path}")
        url = f"{self.api_base}{path}"
        try:
            return api_request(method, url, token=tok, body=body)
        except RestError as e:
            raise RuntimeError(str(e)) from e

    def open_pr(self, repo, base, head, title, body, draft=True, reviewers=None):
        proj, slug = self._parse(repo)
        payload: dict[str, Any] = {
            "title": f"Draft: {title}" if draft else title,
            "description": body,
            "fromRef": {"id": f"refs/heads/{head}"},
            "toRef": {"id": f"refs/heads/{base}"},
        }
        if reviewers:
            payload["reviewers"] = [{"user": {"name": u}} for u in reviewers]
        created = self._req("POST", f"/projects/{proj}/repos/{slug}/pull-requests", payload)
        assert isinstance(created, dict)
        return self._pr_to_pr(repo, created)

    def update_pr(self, repo, number, *, title=None, body=None, draft=None, reviewers=None):
        proj, slug = self._parse(repo)
        current = self.get_pr(repo, number)
        # DC requires the full PR version number for concurrency control.
        full = self._req("GET", f"/projects/{proj}/repos/{slug}/pull-requests/{number}")
        version = int(full.get("version", 0))
        patch: dict[str, Any] = {"version": version}
        if title is not None:
            patch["title"] = f"Draft: {title}" if draft is True else title
        elif draft is False:
            patch["title"] = current.title.removeprefix("Draft: ").removeprefix("WIP: ")
        if body is not None:
            patch["description"] = body
        self._req("PUT", f"/projects/{proj}/repos/{slug}/pull-requests/{number}", patch)
        return self.get_pr(repo, number)

    def get_pr(self, repo, number):
        proj, slug = self._parse(repo)
        pr = self._req("GET", f"/projects/{proj}/repos/{slug}/pull-requests/{number}")
        assert isinstance(pr, dict)
        return self._pr_to_pr(repo, pr)

    def merge_pr(self, repo, number, strategy="merge-commit"):
        proj, slug = self._parse(repo)
        # DC merge endpoint needs the version for concurrency.
        full = self._req("GET", f"/projects/{proj}/repos/{slug}/pull-requests/{number}")
        version = int(full.get("version", 0))
        self._req(
            "POST",
            f"/projects/{proj}/repos/{slug}/pull-requests/{number}/merge?version={version}",
        )
        return self.get_pr(repo, number)

    def close_pr(self, repo, number):
        proj, slug = self._parse(repo)
        full = self._req("GET", f"/projects/{proj}/repos/{slug}/pull-requests/{number}")
        version = int(full.get("version", 0))
        self._req(
            "POST",
            f"/projects/{proj}/repos/{slug}/pull-requests/{number}/decline?version={version}",
        )
        return self.get_pr(repo, number)

    def list_checks(self, repo, ref):
        proj, slug = self._parse(repo)
        try:
            data = self._req(
                "GET", f"/projects/{proj}/repos/{slug}/commits/{ref}/builds"
            )
            return data.get("values", []) if isinstance(data, dict) else []
        except Exception:
            return []

    def enqueue_merge(self, repo, number):
        return False  # no merge queue

    def _pr_to_pr(self, repo: str, pr: dict[str, Any]) -> PullRequest:
        raw_state = str(pr.get("state") or "").upper()  # OPEN|MERGED|DECLINED
        title = str(pr.get("title") or "")
        draft = title.lower().startswith(("draft:", "wip:"))
        if raw_state == "MERGED":
            state = "merged"
        elif raw_state == "DECLINED":
            state = "closed"
        elif draft:
            state = "draft"
        else:
            state = "open"

        links = (pr.get("links") or {}).get("self") or []
        url = links[0].get("href") if links else ""
        reviewers = [
            (r.get("user") or {}).get("name") or ""
            for r in (pr.get("reviewers") or [])
        ]
        return PullRequest(
            host=self.host_id,
            repo=repo,
            number=int(pr.get("id") or 0),
            url=str(url),
            state=state,
            title=title,
            body=str(pr.get("description") or ""),
            base=str((pr.get("toRef") or {}).get("displayId") or ""),
            head=str((pr.get("fromRef") or {}).get("displayId") or ""),
            reviewers=reviewers,
        )
