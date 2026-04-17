"""
Host adapters for the 9 non-GitHub hosts.

Every op raises NotImplementedHostOp with a descriptive message so
pr-lifecycle can fall back gracefully (e.g., skip PR open, leave a
note in the branch metadata, or emit a "manual handoff required"
event on the bus).

This is Phase-2-of-Phase-1: the plugin surface is complete; the
per-host implementation lands per milestone in the roadmap. When you
implement one, replace the stub class in this file with a real
adapter in its own module (e.g., `shared/scripts/adapters/gitlab.py`) and
wire it in the factory in `__init__.py`.
"""

from __future__ import annotations

from typing import Any

from . import HostAdapter, NotImplementedHostOp, PullRequest


def _raise(host: str, op: str):
    raise NotImplementedHostOp(host, op)


class _StubBase(HostAdapter):
    host_id = "stub"

    def is_authenticated(self) -> bool:
        return False

    def open_pr(self, repo, base, head, title, body, draft=True, reviewers=None):
        _raise(self.host_id, "open_pr")

    def update_pr(self, repo, number, **kw):
        _raise(self.host_id, "update_pr")

    def get_pr(self, repo, number):
        _raise(self.host_id, "get_pr")

    def merge_pr(self, repo, number, strategy="merge-commit"):
        _raise(self.host_id, "merge_pr")

    def list_checks(self, repo, ref):
        _raise(self.host_id, "list_checks")

    def enqueue_merge(self, repo, number):
        _raise(self.host_id, "enqueue_merge")


class GitLabAdapter(_StubBase):
    host_id = "gitlab"


class BitbucketCloudAdapter(_StubBase):
    host_id = "bitbucket-cloud"


class BitbucketDataCenterAdapter(_StubBase):
    host_id = "bitbucket-dc"


class AzureDevOpsAdapter(_StubBase):
    host_id = "azure-devops"


class GiteaAdapter(_StubBase):
    host_id = "gitea"


class ForgejoAdapter(_StubBase):
    host_id = "forgejo"


class CodebergAdapter(_StubBase):
    host_id = "codeberg"


class CodeCommitAdapter(_StubBase):
    host_id = "codecommit"


class SourceHutAdapter(_StubBase):
    """SourceHut uses mailing-list PRs — can never implement open_pr in the
    `POST /pulls` sense. This adapter will ship as a patch-email generator
    that produces `git format-patch` output for `git send-email`. Until
    then, all ops raise."""
    host_id = "sourcehut"
