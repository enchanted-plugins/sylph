"""
GitHub host adapter.

Delegates to the `gh` CLI so we inherit its device-flow auth, keychain
integration, and GitHub App token handling without reimplementing the
API client ourselves (same pattern as `gh` itself uses for the `git`
subprocess). When `gh` is not installed, the adapter reports
is_authenticated() == False and every op raises NotImplementedHostOp.

Stdlib only. `gh` is an optional runtime dep documented in install.sh.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from . import HostAdapter, NotImplementedHostOp, PullRequest


class GitHubAdapter(HostAdapter):
    host_id = "github"

    def __init__(self, gh_bin: str = "gh"):
        self.gh = gh_bin

    # ── Auth ────────────────────────────────────────────────────────────

    def _gh_available(self) -> bool:
        return shutil.which(self.gh) is not None

    def is_authenticated(self) -> bool:
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

    def _require_gh(self, op: str) -> None:
        if not self._gh_available():
            raise NotImplementedHostOp(self.host_id, f"{op}: `gh` CLI not on PATH")
        if not self.is_authenticated():
            raise NotImplementedHostOp(self.host_id, f"{op}: `gh` not authenticated (run `gh auth login`)")

    def _gh_api(self, *args: str, timeout: float = 30.0) -> dict[str, Any]:
        """Invoke `gh api` and parse JSON. Raises on non-zero exit."""
        r = subprocess.run(
            [self.gh, "api", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if r.returncode != 0:
            raise RuntimeError(f"gh api failed: {r.stderr.strip()}")
        return json.loads(r.stdout or "{}")

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
        self._require_gh("open_pr")
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

        # `gh pr create` prints the PR URL on stdout; reparse into a PR.
        url = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
        number = self._parse_pr_number_from_url(url) or 0
        if number == 0:
            # Fall back to `gh pr view` on the current branch to resolve number.
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
        self._require_gh("update_pr")

        if title is not None or body is not None:
            args = [self.gh, "pr", "edit", str(number), "--repo", repo]
            if title is not None:
                args += ["--title", title]
            if body is not None:
                args += ["--body", body]
            r = subprocess.run(args, capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                raise RuntimeError(f"gh pr edit failed: {r.stderr.strip()}")

        if draft is not None:
            sub = "ready" if not draft else "ready --undo"
            r = subprocess.run(
                [self.gh, "pr", sub.split()[0], str(number), "--repo", repo]
                + (sub.split()[1:] or []),
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode != 0 and "already" not in r.stderr.lower():
                raise RuntimeError(f"gh pr ready toggle failed: {r.stderr.strip()}")

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
        self._require_gh("get_pr")
        fields = "number,url,state,title,body,baseRefName,headRefName,isDraft,reviewRequests,latestReviews,statusCheckRollup"
        r = subprocess.run(
            [self.gh, "pr", "view", str(number), "--repo", repo,
             "--json", fields],
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

    def merge_pr(
        self,
        repo: str,
        number: int,
        strategy: str = "merge-commit",
    ) -> PullRequest:
        self._require_gh("merge_pr")
        flag_map = {
            "merge-commit": "--merge",
            "squash": "--squash",
            "rebase": "--rebase",
        }
        flag = flag_map.get(strategy)
        if not flag:
            raise ValueError(f"unknown strategy: {strategy}")

        r = subprocess.run(
            [self.gh, "pr", "merge", str(number), "--repo", repo, flag, "--delete-branch"],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            raise RuntimeError(f"gh pr merge failed: {r.stderr.strip()}")

        return self.get_pr(repo, number)

    def list_checks(self, repo: str, ref: str) -> list[dict[str, Any]]:
        self._require_gh("list_checks")
        # `gh api` Check Runs API. Ref can be a SHA or branch.
        data = self._gh_api(f"repos/{repo}/commits/{ref}/check-runs")
        return data.get("check_runs") or []

    def enqueue_merge(self, repo: str, number: int) -> bool:
        self._require_gh("enqueue_merge")
        # GitHub Merge Queue enqueue: `gh pr merge --auto` enables auto-merge
        # which enqueues once required checks pass. Returns True if the PR
        # now has auto-merge enabled (or is already in the queue).
        r = subprocess.run(
            [self.gh, "pr", "merge", str(number), "--repo", repo,
             "--auto", "--merge"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            return True
        # Some errors are benign (already auto-merging, queue not enabled).
        err = r.stderr.lower()
        if "auto merge" in err and "already" in err:
            return True
        if "merge queue" not in err and "not enabled" not in err:
            raise RuntimeError(f"gh pr merge --auto failed: {r.stderr.strip()}")
        return False

    # ── helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _parse_pr_number_from_url(url: str) -> int | None:
        import re as _re
        m = _re.search(r"/pull/(\d+)", url)
        return int(m.group(1)) if m else None
