"""
Gitea adapter (and Forgejo + Codeberg — identical API).

Gitea exposes a GitHub-compatible subset. Same JSON shape for pulls +
issues, token auth via Authorization header. Key differences:
  - API base is `/api/v1` (vs GitHub's `/api/v3` or direct v3 semantics).
  - Auth header: `token <TOKEN>` (not `Bearer`).
  - Review requests live on the PR object itself (not a separate endpoint).

Forgejo is a soft-fork and Codeberg hosts Forgejo — both speak this API.

Token resolution: $GITEA_TOKEN, $FORGEJO_TOKEN (for the two subclasses),
or git credential-manager for the configured host.
"""

from __future__ import annotations

from typing import Any

from . import HostAdapter, NotImplementedHostOp, PullRequest
from ._rest import api_request, resolve_token, RestError
from registry_loader import get_host


class GiteaAdapter(HostAdapter):
    host_id = "gitea"
    _env_vars = ["GITEA_TOKEN"]
    _default_host = "gitea.example.com"  # No SaaS — callers must set credential_host
    # Which capability-registry entry to consult for defaults. Subclasses
    # override (forgejo, codeberg).
    _registry_id = "gitea"

    def __init__(
        self,
        token: str | None = None,
        api_base: str | None = None,
        credential_host: str | None = None,
    ):
        # Registry may carry a placeholder base for self-hosted hosts
        # (gitea/forgejo) or a real SaaS URL (codeberg).
        reg = get_host(self._registry_id)
        reg_base = reg.get("api_base") or ""
        if reg_base and "<" in reg_base:
            # Placeholder like https://<host>/api/v1 — don't use.
            reg_base = ""
        self.api_base = (api_base or reg_base).rstrip("/") or None
        self.credential_host = credential_host or self._default_host
        self._token_explicit = token
        self._token_cached: str | None = None
        self._token_probed = False

    def _token(self) -> str | None:
        if self._token_explicit:
            return self._token_explicit
        if not self._token_probed:
            self._token_cached = resolve_token(self._env_vars, self.credential_host)
            self._token_probed = True
        return self._token_cached

    def is_authenticated(self) -> bool:
        return bool(self._token()) and bool(self.api_base)

    def _require_auth(self, op: str) -> str:
        if not self.api_base:
            raise NotImplementedHostOp(
                self.host_id,
                f"{op}: no api_base configured (set via constructor or capability registry)",
            )
        tok = self._token()
        if not tok:
            raise NotImplementedHostOp(
                self.host_id,
                f"{op}: no token (set {'/'.join(self._env_vars)} or configure git credential-manager)",
            )
        return tok

    # Gitea uses "token ..." not "Bearer ..." for auth.
    def _req(self, method: str, path: str, body: Any = None) -> Any:
        tok = self._require_auth(method + " " + path)
        url = f"{self.api_base}{path}"
        try:
            return api_request(
                method, url, token=tok, auth_scheme="token",
                body=body if body is not None else None,
            )
        except RestError as e:
            raise RuntimeError(str(e)) from e

    # ── PR ops ─────────────────────────────────────────────────────────

    def open_pr(self, repo, base, head, title, body, draft=True, reviewers=None):
        payload: dict[str, Any] = {
            "base": base,
            "head": head,
            "title": title,
            "body": body,
        }
        # Gitea doesn't have a native draft flag on create — prefix title instead.
        if draft:
            payload["title"] = f"WIP: {title}"
        created = self._req("POST", f"/repos/{repo}/pulls", payload)
        assert isinstance(created, dict)
        number = int(created.get("number") or 0)

        if reviewers:
            try:
                self._req(
                    "POST",
                    f"/repos/{repo}/pulls/{number}/requested_reviewers",
                    {"reviewers": reviewers},
                )
            except Exception:
                pass

        return self.get_pr(repo, number)

    def update_pr(self, repo, number, *, title=None, body=None, draft=None, reviewers=None):
        patch: dict[str, Any] = {}
        if title is not None:
            patch["title"] = f"WIP: {title}" if draft is True else title
        if body is not None:
            patch["body"] = body
        if draft is False and title is None:
            # Strip WIP prefix
            current = self.get_pr(repo, number).title
            patch["title"] = current.removeprefix("WIP: ").removeprefix("Draft: ")
        if patch:
            self._req("PATCH", f"/repos/{repo}/pulls/{number}", patch)
        if reviewers:
            try:
                self._req(
                    "POST",
                    f"/repos/{repo}/pulls/{number}/requested_reviewers",
                    {"reviewers": reviewers},
                )
            except Exception:
                pass
        return self.get_pr(repo, number)

    def get_pr(self, repo, number):
        pr = self._req("GET", f"/repos/{repo}/pulls/{number}")
        assert isinstance(pr, dict)
        return self._pr_to_pr(repo, number, pr)

    def merge_pr(self, repo, number, strategy="merge-commit"):
        style_map = {"merge-commit": "merge", "squash": "squash", "rebase": "rebase"}
        style = style_map.get(strategy)
        if not style:
            raise ValueError(f"unknown strategy: {strategy}")
        self._req("POST", f"/repos/{repo}/pulls/{number}/merge", {"Do": style})
        return self.get_pr(repo, number)

    def close_pr(self, repo, number):
        self._req("PATCH", f"/repos/{repo}/pulls/{number}", {"state": "closed"})
        return self.get_pr(repo, number)

    def list_checks(self, repo, ref):
        # Gitea has limited CI — most teams use external runners. Return empty
        # when the endpoint isn't available; ci-reader's adapter will fill in
        # separately if a real CI is configured.
        try:
            data = self._req("GET", f"/repos/{repo}/commits/{ref}/statuses")
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def enqueue_merge(self, repo, number):
        # Gitea has no merge-queue concept. Return False rather than raise so
        # the caller can fall back to a direct merge_pr.
        return False

    # ── helpers ────────────────────────────────────────────────────────

    def _pr_to_pr(self, repo: str, fallback_number: int, pr: dict[str, Any]) -> PullRequest:
        raw_state = str(pr.get("state") or "").lower()
        merged = bool(pr.get("merged"))
        title = str(pr.get("title") or "")
        draft = title.lower().startswith(("wip:", "draft:"))
        if merged:
            state = "merged"
        elif raw_state == "closed":
            state = "closed"
        elif draft:
            state = "draft"
        else:
            state = "open"

        reviewers = [
            u.get("login") for u in (pr.get("requested_reviewers") or []) if u.get("login")
        ]

        return PullRequest(
            host=self.host_id,
            repo=repo,
            number=int(pr.get("number") or fallback_number),
            url=str(pr.get("html_url") or pr.get("url") or ""),
            state=state,
            title=title,
            body=str(pr.get("body") or ""),
            base=str((pr.get("base") or {}).get("ref") or ""),
            head=str((pr.get("head") or {}).get("ref") or ""),
            reviewers=reviewers,
        )


class ForgejoAdapter(GiteaAdapter):
    host_id = "forgejo"
    _env_vars = ["FORGEJO_TOKEN", "GITEA_TOKEN"]
    _registry_id = "forgejo"


class CodebergAdapter(ForgejoAdapter):
    host_id = "codeberg"
    _default_host = "codeberg.org"
    _registry_id = "codeberg"

    def __init__(self, token=None, api_base=None, credential_host=None):
        # Codeberg's registry entry is a real SaaS base (not a placeholder),
        # so GiteaAdapter.__init__ picks it up without override. The only
        # thing special here is the credential_host default.
        super().__init__(
            token=token,
            api_base=api_base,
            credential_host=credential_host or "codeberg.org",
        )
