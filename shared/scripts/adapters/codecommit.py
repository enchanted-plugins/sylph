"""
AWS CodeCommit adapter.

SigV4 signing in stdlib is ~300 lines of HMAC-SHA256 canonical-request
choreography, and boto3 would add a heavy external dep. We take the
practical middle path: shell out to the `aws codecommit` CLI, which is
already configured on most machines that touch CodeCommit (it reads
~/.aws/credentials / IAM roles / instance metadata).

If `aws` isn't installed or configured, every op raises
NotImplementedHostOp with a clear setup hint.

Note: CodeCommit's strategic importance inside AWS has declined
[verify: Q1 2026]. If it's retired, this adapter stays as a thin
layer over a working toolchain rather than a dead-code stdlib rewrite.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from . import HostAdapter, NotImplementedHostOp, PullRequest


class CodeCommitAdapter(HostAdapter):
    host_id = "codecommit"

    def __init__(self, aws_bin: str = "aws", region: str | None = None):
        self.aws = aws_bin
        self.region = region  # optional; aws CLI picks default from config

    def _aws_available(self) -> bool:
        return shutil.which(self.aws) is not None

    def _aws(self, *args: str, timeout: float = 60.0) -> dict[str, Any]:
        if not self._aws_available():
            raise NotImplementedHostOp(
                self.host_id, "`aws` CLI not on PATH (install AWS CLI v2)"
            )
        cmd = [self.aws, "codecommit", *args, "--output", "json"]
        if self.region:
            cmd += ["--region", self.region]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
            raise NotImplementedHostOp(self.host_id, f"aws cli failed: {e}")
        if r.returncode != 0:
            raise RuntimeError(f"aws codecommit {args[0]} failed: {r.stderr.strip()}")
        try:
            return json.loads(r.stdout or "{}")
        except json.JSONDecodeError:
            return {}

    def is_authenticated(self) -> bool:
        if not self._aws_available():
            return False
        try:
            r = subprocess.run(
                [self.aws, "sts", "get-caller-identity", "--output", "json"],
                capture_output=True, text=True, timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False
        return r.returncode == 0

    # ── PR ops ─────────────────────────────────────────────────────────

    def open_pr(self, repo, base, head, title, body, draft=True, reviewers=None):
        # CodeCommit's CreatePullRequest doesn't carry a native draft flag;
        # we prefix the title, matching every other draft-less host.
        payload_title = f"Draft: {title}" if draft else title
        data = self._aws(
            "create-pull-request",
            "--title", payload_title,
            "--description", body,
            "--targets",
            json.dumps([{
                "repositoryName": repo,
                "sourceReference": head,
                "destinationReference": base,
            }]),
        )
        pr = data.get("pullRequest") or {}
        number = int(pr.get("pullRequestId") or 0)
        # CodeCommit has no native reviewer-request endpoint pre-2020;
        # users are approval-rule-based. Surface the list in the body if given.
        return self.get_pr(repo, number) if number else self._pr_to_pr(repo, pr)

    def update_pr(self, repo, number, *, title=None, body=None, draft=None, reviewers=None):
        if title is not None or draft is not None:
            final_title = title
            if draft is True and title:
                final_title = f"Draft: {title}"
            elif draft is False and title:
                final_title = title.removeprefix("Draft: ").removeprefix("WIP: ")
            elif draft is False and title is None:
                current = self.get_pr(repo, number).title
                final_title = current.removeprefix("Draft: ").removeprefix("WIP: ")
            if final_title is not None:
                self._aws(
                    "update-pull-request-title",
                    "--pull-request-id", str(number),
                    "--title", final_title,
                )
        if body is not None:
            self._aws(
                "update-pull-request-description",
                "--pull-request-id", str(number),
                "--description", body,
            )
        # Reviewers → approval rules are out-of-scope for this adapter.
        return self.get_pr(repo, number)

    def get_pr(self, repo, number):
        data = self._aws("get-pull-request", "--pull-request-id", str(number))
        pr = data.get("pullRequest") or {}
        return self._pr_to_pr(repo, pr)

    def merge_pr(self, repo, number, strategy="merge-commit"):
        action_map = {
            "merge-commit": "merge-pull-request-by-three-way",
            "squash": "merge-pull-request-by-squash",
            "fast-forward": "merge-pull-request-by-fast-forward",
        }
        action = action_map.get(strategy, "merge-pull-request-by-three-way")
        self._aws(
            action,
            "--pull-request-id", str(number),
            "--repository-name", repo,
        )
        return self.get_pr(repo, number)

    def close_pr(self, repo, number):
        self._aws(
            "update-pull-request-status",
            "--pull-request-id", str(number),
            "--pull-request-status", "CLOSED",
        )
        return self.get_pr(repo, number)

    def list_checks(self, repo, ref):
        # CodeCommit doesn't run CI directly; expect CodeBuild via a separate
        # adapter (not yet in ci-reader).
        return []

    def enqueue_merge(self, repo, number):
        return False  # no queue concept

    def _pr_to_pr(self, repo: str, pr: dict[str, Any]) -> PullRequest:
        status = str(pr.get("pullRequestStatus") or "").upper()
        title = str(pr.get("title") or "")
        draft = title.lower().startswith(("draft:", "wip:"))
        if status == "CLOSED":
            # CodeCommit flags merged PRs by inspecting targets[].mergeMetadata.isMerged
            targets = pr.get("pullRequestTargets") or []
            merged = any(
                (t.get("mergeMetadata") or {}).get("isMerged")
                for t in targets
            )
            state = "merged" if merged else "closed"
        elif draft:
            state = "draft"
        else:
            state = "open"

        targets = pr.get("pullRequestTargets") or []
        target0 = targets[0] if targets else {}
        return PullRequest(
            host=self.host_id,
            repo=repo,
            number=int(pr.get("pullRequestId") or 0),
            url="",  # CodeCommit PRs are viewed in the AWS Console; no stable API-returned URL
            state=state,
            title=title,
            body=str(pr.get("description") or ""),
            base=str(target0.get("destinationReference") or "").replace("refs/heads/", ""),
            head=str(target0.get("sourceReference") or "").replace("refs/heads/", ""),
            reviewers=[],  # approval-rule based; not a simple list
        )
