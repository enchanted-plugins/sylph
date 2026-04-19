"""
GitHub host adapter.

Two auth + transport paths, tried in order:
  1. urllib + token (preferred). Token comes from $GH_TOKEN / $GITHUB_TOKEN,
     or `git credential fill` (which surfaces whatever credential-manager
     is already storing for github.com — the same one `git push` uses).
     Stdlib only.
  2. `gh` CLI (fallback). Inherits device-flow auth + keychain handling.

If neither works, every op raises NotImplementedHostOp so callers degrade
cleanly to manual-handoff.

Stdlib only. `gh` is optional.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import HostAdapter, NotImplementedHostOp, PullRequest


API_BASE = "https://api.github.com"
USER_AGENT = "weaver/0.1.0"


# ──────────────────────────────────────────────────────────────────────
# Token resolution
# ──────────────────────────────────────────────────────────────────────

def resolve_token() -> str | None:
    """Return a GitHub token from (in order) GH_TOKEN, GITHUB_TOKEN, or
    `git credential fill` for host=github.com. None if nothing found.

    Broken out as a module-level function so unit tests can mock it
    without going through the adapter constructor.
    """
    for var in ("GH_TOKEN", "GITHUB_TOKEN"):
        tok = os.environ.get(var)
        if tok and tok.strip():
            return tok.strip()

    try:
        r = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None

    if r.returncode != 0:
        return None

    for line in r.stdout.splitlines():
        if line.startswith("password="):
            tok = line[len("password="):]
            return tok if tok else None

    return None


# ──────────────────────────────────────────────────────────────────────
# Adapter
# ──────────────────────────────────────────────────────────────────────


class GitHubAdapter(HostAdapter):
    host_id = "github"

    def __init__(self, gh_bin: str = "gh", token: str | None = None):
        self.gh = gh_bin
        # Explicit token wins; else resolved lazily on first use.
        self._token_explicit = token
        self._token_cached: str | None = None
        self._token_probed = False

    # ── Auth ────────────────────────────────────────────────────────────

    def _token(self) -> str | None:
        if self._token_explicit:
            return self._token_explicit
        if not self._token_probed:
            self._token_cached = resolve_token()
            self._token_probed = True
        return self._token_cached

    def _gh_available(self) -> bool:
        return shutil.which(self.gh) is not None

    def _gh_authenticated(self) -> bool:
        if not self._gh_available():
            return False
        try:
            r = subprocess.run(
                [self.gh, "auth", "status"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False
        return r.returncode == 0

    def is_authenticated(self) -> bool:
        return bool(self._token()) or self._gh_authenticated()

    # ── HTTP helpers (urllib path) ─────────────────────────────────────

    def _api_request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any] | list[Any]:
        """Call the GitHub REST API with the resolved token.

        path is appended to API_BASE (e.g. '/repos/owner/name/pulls').
        Returns parsed JSON (dict or list). Raises urllib.error.HTTPError
        on 4xx/5xx — callers map to NotImplementedHostOp / RuntimeError.
        """
        tok = self._token()
        if not tok:
            raise NotImplementedHostOp(self.host_id, f"{method} {path}: no token (set GH_TOKEN or configure git credential-manager)")

        url = API_BASE + path
        headers = {
            "Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        }
        data: bytes | None = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            # Surface the GitHub error message if present; still raise.
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                err_body = ""
            raise RuntimeError(f"GitHub API {method} {path} failed: {e.code} {e.reason}: {err_body[:500]}") from e

    # ── PR operations ──────────────────────────────────────────────────

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
        if self._token():
            return self._open_pr_urllib(repo, base, head, title, body, draft, reviewers)
        if self._gh_authenticated():
            return self._open_pr_gh(repo, base, head, title, body, draft, reviewers)
        raise NotImplementedHostOp(self.host_id, "open_pr: no token and gh unavailable")

    def _open_pr_urllib(
        self,
        repo: str,
        base: str,
        head: str,
        title: str,
        body: str,
        draft: bool,
        reviewers: list[str] | None,
    ) -> PullRequest:
        created = self._api_request(
            "POST",
            f"/repos/{repo}/pulls",
            body={"title": title, "body": body, "head": head, "base": base, "draft": draft},
        )
        assert isinstance(created, dict)
        number = int(created.get("number") or 0)

        # Request reviewers in a separate call.
        if reviewers and number:
            try:
                self._api_request(
                    "POST",
                    f"/repos/{repo}/pulls/{number}/requested_reviewers",
                    body={"reviewers": reviewers},
                )
            except Exception:
                # Reviewer request failures are non-fatal (unknown user,
                # not a collaborator, etc.). Log via return value later.
                pass

        return self.get_pr(repo, number)

    def _open_pr_gh(
        self,
        repo: str,
        base: str,
        head: str,
        title: str,
        body: str,
        draft: bool,
        reviewers: list[str] | None,
    ) -> PullRequest:
        args = [
            self.gh, "pr", "create",
            "--repo", repo,
            "--base", base,
            "--head", head,
            "--title", title,
            "--body", body,
        ]
        if draft:
            args.append("--draft")
        if reviewers:
            args += ["--reviewer", ",".join(reviewers)]

        r = subprocess.run(args, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(f"gh pr create failed: {r.stderr.strip()}")

        url = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
        number = self._parse_pr_number_from_url(url) or 0
        if number == 0:
            view = subprocess.run(
                [self.gh, "pr", "view", "--repo", repo, "--json", "number,url"],
                capture_output=True, text=True, timeout=15,
            )
            if view.returncode == 0:
                data = json.loads(view.stdout or "{}")
                number = int(data.get("number") or 0)
                url = str(data.get("url") or url)

        return self.get_pr(repo, number) if number else PullRequest(
            host=self.host_id, repo=repo, number=number, url=url,
            state="draft" if draft else "open", title=title, body=body,
            base=base, head=head, reviewers=list(reviewers or []),
        )

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
        if self._token():
            patch: dict[str, Any] = {}
            if title is not None:
                patch["title"] = title
            if body is not None:
                patch["body"] = body
            if draft is False:
                patch["draft"] = False  # GitHub only accepts draft→ready this direction
            if patch:
                self._api_request("PATCH", f"/repos/{repo}/pulls/{number}", body=patch)
            if reviewers:
                try:
                    self._api_request(
                        "POST",
                        f"/repos/{repo}/pulls/{number}/requested_reviewers",
                        body={"reviewers": reviewers},
                    )
                except Exception:
                    pass
            return self.get_pr(repo, number)

        if not self._gh_authenticated():
            raise NotImplementedHostOp(self.host_id, "update_pr: no token and gh unavailable")

        # gh fallback (unchanged from previous implementation)
        if title is not None or body is not None:
            args = [self.gh, "pr", "edit", str(number), "--repo", repo]
            if title is not None:
                args += ["--title", title]
            if body is not None:
                args += ["--body", body]
            r = subprocess.run(args, capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                raise RuntimeError(f"gh pr edit failed: {r.stderr.strip()}")

        if draft is False:
            r = subprocess.run(
                [self.gh, "pr", "ready", str(number), "--repo", repo],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode != 0 and "already" not in r.stderr.lower():
                raise RuntimeError(f"gh pr ready failed: {r.stderr.strip()}")

        if reviewers:
            r = subprocess.run(
                [self.gh, "pr", "edit", str(number), "--repo", repo,
                 "--add-reviewer", ",".join(reviewers)],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode != 0:
                raise RuntimeError(f"gh pr edit reviewers failed: {r.stderr.strip()}")

        return self.get_pr(repo, number)

    def get_pr(self, repo: str, number: int) -> PullRequest:
        if self._token():
            pr = self._api_request("GET", f"/repos/{repo}/pulls/{number}")
            assert isinstance(pr, dict)
            return self._pr_from_api_dict(repo, number, pr)
        if self._gh_authenticated():
            return self._get_pr_gh(repo, number)
        raise NotImplementedHostOp(self.host_id, "get_pr: no token and gh unavailable")

    def _get_pr_gh(self, repo: str, number: int) -> PullRequest:
        fields = "number,url,state,title,body,baseRefName,headRefName,isDraft,reviewRequests,latestReviews,statusCheckRollup"
        r = subprocess.run(
            [self.gh, "pr", "view", str(number), "--repo", repo, "--json", fields],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            raise RuntimeError(f"gh pr view failed: {r.stderr.strip()}")

        d = json.loads(r.stdout or "{}")
        reviewers = [
            (rr.get("requestedReviewer") or {}).get("login")
            for rr in d.get("reviewRequests") or []
        ]
        reviewers = [u for u in reviewers if u]
        checks = d.get("statusCheckRollup") or []

        state_raw = (d.get("state") or "").lower()
        is_draft = bool(d.get("isDraft"))
        if is_draft:
            state = "draft"
        elif state_raw == "merged":
            state = "merged"
        elif state_raw == "closed":
            state = "closed"
        else:
            state = "open"

        return PullRequest(
            host=self.host_id,
            repo=repo,
            number=int(d.get("number") or number),
            url=str(d.get("url") or ""),
            state=state,
            title=str(d.get("title") or ""),
            body=str(d.get("body") or ""),
            base=str(d.get("baseRefName") or ""),
            head=str(d.get("headRefName") or ""),
            reviewers=reviewers,
            checks=checks,
        )

    def _pr_from_api_dict(self, repo: str, fallback_number: int, pr: dict[str, Any]) -> PullRequest:
        """Normalize a GitHub REST pulls/{n} payload into a PullRequest."""
        number = int(pr.get("number") or fallback_number)

        state_raw = (pr.get("state") or "").lower()  # "open" | "closed"
        is_draft = bool(pr.get("draft"))
        merged = bool(pr.get("merged"))
        if is_draft:
            state = "draft"
        elif merged:
            state = "merged"
        elif state_raw == "closed":
            state = "closed"
        else:
            state = "open"

        reviewers = [
            u.get("login")
            for u in (pr.get("requested_reviewers") or [])
            if u.get("login")
        ]

        return PullRequest(
            host=self.host_id,
            repo=repo,
            number=number,
            url=str(pr.get("html_url") or pr.get("url") or ""),
            state=state,
            title=str(pr.get("title") or ""),
            body=str(pr.get("body") or ""),
            base=str((pr.get("base") or {}).get("ref") or ""),
            head=str((pr.get("head") or {}).get("ref") or ""),
            reviewers=reviewers,
        )

    def merge_pr(
        self,
        repo: str,
        number: int,
        strategy: str = "merge-commit",
    ) -> PullRequest:
        api_method_map = {"merge-commit": "merge", "squash": "squash", "rebase": "rebase"}
        if strategy not in api_method_map:
            raise ValueError(f"unknown strategy: {strategy}")

        if self._token():
            self._api_request(
                "PUT",
                f"/repos/{repo}/pulls/{number}/merge",
                body={"merge_method": api_method_map[strategy]},
            )
            return self.get_pr(repo, number)

        if not self._gh_authenticated():
            raise NotImplementedHostOp(self.host_id, "merge_pr: no token and gh unavailable")

        flag_map = {"merge-commit": "--merge", "squash": "--squash", "rebase": "--rebase"}
        r = subprocess.run(
            [self.gh, "pr", "merge", str(number), "--repo", repo,
             flag_map[strategy], "--delete-branch"],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            raise RuntimeError(f"gh pr merge failed: {r.stderr.strip()}")
        return self.get_pr(repo, number)

    def close_pr(self, repo: str, number: int) -> PullRequest:
        """Close a PR without merging (useful for cleanup in tests). Not
        part of the formal HostAdapter contract but exposed here for
        weaver-owned integration tests."""
        if self._token():
            self._api_request(
                "PATCH",
                f"/repos/{repo}/pulls/{number}",
                body={"state": "closed"},
            )
            return self.get_pr(repo, number)
        if not self._gh_authenticated():
            raise NotImplementedHostOp(self.host_id, "close_pr: no token and gh unavailable")
        r = subprocess.run(
            [self.gh, "pr", "close", str(number), "--repo", repo],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            raise RuntimeError(f"gh pr close failed: {r.stderr.strip()}")
        return self.get_pr(repo, number)

    def list_checks(self, repo: str, ref: str) -> list[dict[str, Any]]:
        if self._token():
            data = self._api_request("GET", f"/repos/{repo}/commits/{ref}/check-runs")
            assert isinstance(data, dict)
            return data.get("check_runs") or []
        if not self._gh_authenticated():
            raise NotImplementedHostOp(self.host_id, "list_checks: no token and gh unavailable")
        r = subprocess.run(
            [self.gh, "api", f"repos/{repo}/commits/{ref}/check-runs"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            raise RuntimeError(f"gh api failed: {r.stderr.strip()}")
        data = json.loads(r.stdout or "{}")
        return data.get("check_runs") or []

    def enqueue_merge(self, repo: str, number: int) -> bool:
        """Enable auto-merge (GitHub Merge Queue). Requires GraphQL on the
        urllib path because enabling auto-merge isn't a REST endpoint.
        Falls back to `gh pr merge --auto` when gh is available."""
        if self._gh_authenticated():
            r = subprocess.run(
                [self.gh, "pr", "merge", str(number), "--repo", repo,
                 "--auto", "--merge"],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode == 0:
                return True
            err = r.stderr.lower()
            if "auto merge" in err and "already" in err:
                return True
            if "merge queue" not in err and "not enabled" not in err:
                raise RuntimeError(f"gh pr merge --auto failed: {r.stderr.strip()}")
            return False

        if not self._token():
            raise NotImplementedHostOp(self.host_id, "enqueue_merge: no token and gh unavailable")

        # urllib path: GraphQL enablePullRequestAutoMerge.
        # First get the PR node id.
        pr = self._api_request("GET", f"/repos/{repo}/pulls/{number}")
        assert isinstance(pr, dict)
        pr_node_id = pr.get("node_id")
        if not pr_node_id:
            return False

        mutation = {
            "query": (
                "mutation($id: ID!) { "
                "enablePullRequestAutoMerge(input: {pullRequestId: $id, mergeMethod: MERGE}) "
                "{ pullRequest { id } } }"
            ),
            "variables": {"id": pr_node_id},
        }
        try:
            self._api_request("POST", "/graphql", body=mutation)
            return True
        except Exception:
            return False

    # ── helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _parse_pr_number_from_url(url: str) -> int | None:
        m = re.search(r"/pull/(\d+)", url)
        return int(m.group(1)) if m else None
