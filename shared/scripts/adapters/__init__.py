"""
Weaver host-adapter package.

Provides a typed interface for git-host operations (open PR, merge, list
checks, resolve CODEOWNERS) plus a registry that picks the right adapter
for a given remote URL.

Each host implements a subset of HostAdapter. Unimplemented methods raise
NotImplementedHostOp — the caller (pr-lifecycle etc.) decides whether to
degrade or surface the gap.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class NotImplementedHostOp(Exception):
    """Raised when a host adapter lacks the requested operation."""

    def __init__(self, host_id: str, op: str):
        super().__init__(f"{host_id}: {op} not implemented")
        self.host_id = host_id
        self.op = op


@dataclass
class PullRequest:
    """Normalized PR representation across hosts."""
    host: str
    repo: str            # "owner/name"
    number: int
    url: str
    state: str           # "draft" | "open" | "closed" | "merged"
    title: str
    body: str
    base: str
    head: str
    reviewers: list[str] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "repo": self.repo,
            "number": self.number,
            "url": self.url,
            "state": self.state,
            "title": self.title,
            "body": self.body,
            "base": self.base,
            "head": self.head,
            "reviewers": list(self.reviewers),
            "checks": list(self.checks),
        }


class HostAdapter(ABC):
    """Contract every host adapter implements. Unimplemented ops raise."""

    host_id: str = "unknown"

    @abstractmethod
    def is_authenticated(self) -> bool:
        """Return True if credentials are available to call the API."""

    @abstractmethod
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
        """Open a new PR. Raises NotImplementedHostOp if unsupported."""

    @abstractmethod
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
        """Update an existing PR. Raises NotImplementedHostOp if unsupported."""

    @abstractmethod
    def get_pr(self, repo: str, number: int) -> PullRequest:
        """Fetch a PR's current state."""

    @abstractmethod
    def merge_pr(
        self,
        repo: str,
        number: int,
        strategy: str = "merge-commit",
    ) -> PullRequest:
        """Merge a PR with the given strategy. May raise if the strategy
        isn't in the host's capability registry."""

    @abstractmethod
    def list_checks(self, repo: str, ref: str) -> list[dict[str, Any]]:
        """Return check runs / pipeline status for a ref."""

    @abstractmethod
    def enqueue_merge(self, repo: str, number: int) -> bool:
        """GitHub Merge Queue / GitLab Merge Train equivalent. Returns
        True if enqueued; raises NotImplementedHostOp if the host has no
        queue concept."""


# ──────────────────────────────────────────────────────────────────────
# Remote URL detection
# ──────────────────────────────────────────────────────────────────────

_REMOTE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"github\.com[:/]"), "github"),
    (re.compile(r"gitlab\.com[:/]|gitlab\."), "gitlab"),
    (re.compile(r"bitbucket\.org[:/]"), "bitbucket-cloud"),
    (re.compile(r"bitbucket\."), "bitbucket-dc"),
    (re.compile(r"dev\.azure\.com|visualstudio\.com"), "azure-devops"),
    (re.compile(r"codeberg\.org[:/]"), "codeberg"),
    (re.compile(r"codecommit\..*\.amazonaws\.com"), "codecommit"),
    (re.compile(r"git\.sr\.ht[:/]"), "sourcehut"),
]


def detect_host(remote_url: str) -> str:
    """Best-effort: pick a host id for a remote URL. Defaults to 'unknown'."""
    for pat, host_id in _REMOTE_PATTERNS:
        if pat.search(remote_url):
            return host_id
    # Self-hosted Gitea / Forgejo fall through — caller should probe
    # /api/v1/version to distinguish if it matters.
    return "unknown"


def parse_github_repo(remote_url: str) -> str | None:
    """Extract owner/name from a GitHub remote URL. None if not parseable."""
    # SSH: git@github.com:owner/name.git
    m = re.match(r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$", remote_url.strip())
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    # HTTPS: https://github.com/owner/name.git
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", remote_url.strip())
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    return None


def get_adapter(host_id: str) -> HostAdapter:
    """Factory: return the adapter for a host id. Raises KeyError for unknowns.

    All 10 hosts have real adapter implementations. Availability at runtime
    depends on credentials / tooling being present; each adapter's
    is_authenticated() reports that and raises NotImplementedHostOp on
    op invocation when unavailable.
    """
    if host_id == "github":
        from . import github as _gh
        return _gh.GitHubAdapter()
    if host_id == "gitlab":
        from . import gitlab as _gl
        return _gl.GitLabAdapter()
    if host_id == "bitbucket-cloud":
        from . import bitbucket as _bb
        return _bb.BitbucketCloudAdapter()
    if host_id == "bitbucket-dc":
        from . import bitbucket as _bb
        return _bb.BitbucketDataCenterAdapter()
    if host_id == "azure-devops":
        from . import azure_devops as _ado
        return _ado.AzureDevOpsAdapter()
    if host_id == "gitea":
        from . import gitea as _gt
        return _gt.GiteaAdapter()
    if host_id == "forgejo":
        from . import gitea as _gt
        return _gt.ForgejoAdapter()
    if host_id == "codeberg":
        from . import gitea as _gt
        return _gt.CodebergAdapter()
    if host_id == "codecommit":
        from . import codecommit as _cc
        return _cc.CodeCommitAdapter()
    if host_id == "sourcehut":
        from . import sourcehut as _sh
        return _sh.SourceHutAdapter()

    raise KeyError(f"unknown host id: {host_id}")
