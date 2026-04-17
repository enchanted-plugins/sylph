"""
W4 — PR lifecycle orchestrator.

Idempotent state machine that drives a PR from drafting → ready → reviewing
→ approved → queued → merged | closed.

The orchestrator is adapter-agnostic: it calls into
`shared/scripts/adapters/<host>.py` via the HostAdapter interface. GitHub is fully
implemented; 9 other hosts stub and raise NotImplementedHostOp, which the
orchestrator catches and reports as "manual handoff required" without
crashing the flow.

Stdlib only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# Late imports — keep the module lightweight until actually used.


# ──────────────────────────────────────────────────────────────────────
# State machine
# ──────────────────────────────────────────────────────────────────────

STATES = ("drafting", "ready", "reviewing", "approved", "queued", "merged", "closed")


@dataclass
class PRDescription:
    title: str
    body: str

    @classmethod
    def from_cluster(
        cls,
        cluster: dict[str, Any] | None,
        commits: list[dict[str, str]] | None = None,
        session_continuity: dict[str, Any] | None = None,
    ) -> "PRDescription":
        """Build a PR title + body from a W2 cluster + commit messages +
        optional Hornet V4 session-continuity data.

        Falls back gracefully when V4 is unavailable.
        """
        commits = commits or []
        cluster = cluster or {}

        # Title: prefer the last commit's subject (Conventional Commits
        # style), falling back to the first file + top token.
        title = ""
        if commits:
            title = commits[-1].get("subject", "").strip()

        if not title and cluster.get("events"):
            files = sorted({
                f for e in cluster["events"] for f in e.get("files", [])
            })
            if files:
                top_token = _top_token_from_cluster(cluster)
                slug = files[0].split("/")[-1].rsplit(".", 1)[0]
                title = f"chore({slug}): {top_token}" if top_token else f"chore({slug}): update"

        if not title:
            title = "chore: weaver-drafted PR"

        # Body: structured markdown. Fall back when V4 is missing.
        body_parts: list[str] = []

        body_parts.append("## What changed\n")
        if commits:
            for c in commits:
                body_parts.append(f"- `{c.get('sha', '')[:8]}` — {c.get('subject', '')}")
        elif cluster.get("events"):
            files = sorted({
                f for e in cluster["events"] for f in e.get("files", [])
            })
            body_parts += [f"- `{p}`" for p in files]
        else:
            body_parts.append("- (commits not available)")

        body_parts.append("")

        if session_continuity:
            body_parts.append("## Why\n")
            decisions = session_continuity.get("decisions") or []
            for d in decisions[:5]:
                body_parts.append(f"- {d}")
            body_parts.append("")

            body_parts.append("## How it was verified\n")
            verified = session_continuity.get("verified") or []
            if verified:
                for v in verified[:5]:
                    body_parts.append(f"- {v}")
            else:
                body_parts.append("_Not recorded in session continuity._")
            body_parts.append("")
        else:
            body_parts.append("## Why\n")
            body_parts.append(
                "_Hornet V4 session-continuity data unavailable — this PR description "
                "reflects W2 cluster metadata + commit messages only. Install hornet "
                "to upgrade._\n"
            )
            body_parts.append("## How it was verified\n")
            body_parts.append(
                "_Inspection only — reviewer should run the test suite before merging._\n"
            )

        # Rollback plan — always compute from commits.
        body_parts.append("## Rollback plan\n")
        if commits:
            shas = " ".join(c.get("sha", "")[:8] for c in commits if c.get("sha"))
            body_parts.append(
                f"```\ngit revert --no-commit {shas}\ngit commit -m \"Revert: {title}\"\n```"
            )
        else:
            body_parts.append("_`git revert <sha>` on the relevant commits._")

        body_parts.append("")
        body_parts.append(
            "---\n*Opened by [Weaver](https://github.com/enchanted-plugins/weaver) (W4 pr-lifecycle).*"
        )

        return cls(title=title[:72], body="\n".join(body_parts))


def _top_token_from_cluster(cluster: dict[str, Any]) -> str:
    """Pick the highest-weighted token across the cluster's events."""
    tally: dict[str, float] = {}
    for e in cluster.get("events", []):
        for k, v in (e.get("vector") or {}).items():
            tally[k] = tally.get(k, 0.0) + float(v)
    if not tally:
        return ""
    return max(tally.items(), key=lambda kv: kv[1])[0]


# ──────────────────────────────────────────────────────────────────────
# Orchestration
# ──────────────────────────────────────────────────────────────────────

def _git(*args: str, cwd: Path | None = None, timeout: float = 15.0) -> tuple[int, str]:
    try:
        r = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.returncode, r.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return -1, ""


def current_branch(cwd: Path) -> str:
    rc, out = _git("branch", "--show-current", cwd=cwd)
    return out.strip() if rc == 0 else ""


def remote_url(cwd: Path, remote: str = "origin") -> str:
    rc, out = _git("remote", "get-url", remote, cwd=cwd)
    return out.strip() if rc == 0 else ""


def default_branch(cwd: Path) -> str:
    """Best-effort default branch name ('main' / 'master' / 'trunk')."""
    # Try origin/HEAD first.
    rc, out = _git("symbolic-ref", "refs/remotes/origin/HEAD", cwd=cwd)
    if rc == 0 and out.strip():
        # "refs/remotes/origin/main" → "main"
        return out.strip().rsplit("/", 1)[-1]
    # Fall back to common names.
    for name in ("main", "master", "trunk"):
        rc, _ = _git("rev-parse", "--verify", f"refs/heads/{name}", cwd=cwd)
        if rc == 0:
            return name
    return "main"


def collect_commits(cwd: Path, base: str, head: str) -> list[dict[str, str]]:
    """`git log base..head` → list of {sha, subject, author}."""
    rc, out = _git(
        "log", f"--format=%H%x09%s%x09%an", f"{base}..{head}", cwd=cwd,
    )
    if rc != 0:
        return []
    commits: list[dict[str, str]] = []
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) >= 2:
            commits.append({"sha": parts[0], "subject": parts[1], "author": parts[2] if len(parts) > 2 else ""})
    commits.reverse()  # oldest-first for the body
    return commits


def collect_changed_paths(cwd: Path, base: str, head: str) -> list[str]:
    rc, out = _git("diff", "--name-only", f"{base}...{head}", cwd=cwd)
    if rc != 0:
        return []
    return [p for p in out.splitlines() if p.strip()]


# ──────────────────────────────────────────────────────────────────────
# Top-level actions (consumed by /weaver:pr)
# ──────────────────────────────────────────────────────────────────────

def open_or_update(
    cwd: Path,
    *,
    base: str | None = None,
    head: str | None = None,
    draft: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Open a draft PR for the current branch (or update if one exists).

    Resolves: host adapter, base/head, reviewer routing, PR description.
    Returns a normalized result dict.
    """
    # Lazy imports to keep stdlib cold-start cheap.
    sys.path.insert(0, str(Path(__file__).parent))
    from adapters import detect_host, parse_github_repo, get_adapter, NotImplementedHostOp
    import reviewer_route  # local module

    url = remote_url(cwd)
    if not url:
        return {"error": "no origin remote set", "stage": "detect-remote"}

    host_id = detect_host(url)
    if host_id == "unknown":
        return {
            "error": f"remote host not recognized: {url}",
            "stage": "detect-host",
            "manual_handoff": True,
        }

    head = head or current_branch(cwd)
    base = base or default_branch(cwd)
    if not head:
        return {"error": "could not determine current branch", "stage": "detect-head"}

    # Load W2 cluster state (if boundary-segmenter is installed).
    # Plugin root is inferred: cwd / plugins / boundary-segmenter / state.
    cluster_state = _try_load_cluster_state(cwd)

    # Gather commits and paths in the range.
    commits = collect_commits(cwd, f"origin/{base}", head)
    paths = collect_changed_paths(cwd, f"origin/{base}", head)
    if not paths and not commits:
        # Possibly a first push; try without origin/ prefix.
        commits = collect_commits(cwd, base, head)
        paths = collect_changed_paths(cwd, base, head)

    # Compose description.
    desc = PRDescription.from_cluster(
        cluster=cluster_state.get("last_closed_cluster") if cluster_state else None,
        commits=commits,
        session_continuity=_try_load_session_continuity(cwd),
    )

    # Rank reviewers.
    reviewer_suggestions = reviewer_route.suggest(paths, cwd, max_suggest=3)
    reviewer_handles = [
        r["identity"].lstrip("@") for r in reviewer_suggestions
        if r["identity"].startswith("@")
    ]

    if dry_run:
        return {
            "dry_run": True,
            "host": host_id,
            "base": base,
            "head": head,
            "title": desc.title,
            "body": desc.body,
            "reviewers": reviewer_handles,
            "reviewer_ranking": reviewer_suggestions,
            "changed_paths": paths,
            "commits": commits,
        }

    # Dispatch to adapter.
    try:
        adapter = get_adapter(host_id)
    except KeyError as e:
        return {"error": str(e), "stage": "get-adapter"}

    if not adapter.is_authenticated():
        return {
            "error": f"{host_id} adapter not authenticated",
            "stage": "authenticate",
            "manual_handoff": True,
            "suggested_action": "run `gh auth login` (GitHub) or set up the host-specific credential helper",
        }

    repo = parse_github_repo(url) if host_id == "github" else None
    if repo is None and host_id == "github":
        return {"error": f"could not parse owner/repo from: {url}", "stage": "parse-repo"}

    try:
        pr = adapter.open_pr(
            repo=repo or "",
            base=base,
            head=head,
            title=desc.title,
            body=desc.body,
            draft=draft,
            reviewers=reviewer_handles or None,
        )
        return {"opened": True, "pr": pr.to_dict(), "reviewer_ranking": reviewer_suggestions}
    except NotImplementedHostOp as e:
        return {
            "error": str(e),
            "stage": "open-pr",
            "manual_handoff": True,
        }
    except Exception as e:
        return {"error": f"adapter error: {e}", "stage": "open-pr"}


def _try_load_cluster_state(cwd: Path) -> dict[str, Any] | None:
    """Load the W2 cluster state if boundary-segmenter is installed locally."""
    # Look for the cluster state in plugins/boundary-segmenter/state/.
    # When called from a hook, the plugin path may be absolute; when called
    # from /weaver:pr in the repo being worked on, the state file is under
    # the plugin install location, not the repo — so this returns None and
    # the PR description falls back to commits-only mode.
    possible = cwd / "plugins" / "boundary-segmenter" / "state" / "boundary-clusters.json"
    if possible.exists():
        try:
            with open(possible, "r", encoding="utf-8") as f:
                state = json.load(f)
            if state.get("closed_clusters"):
                state["last_closed_cluster"] = state["closed_clusters"][-1]
            return state
        except Exception:
            return None
    return None


def _try_load_session_continuity(cwd: Path) -> dict[str, Any] | None:
    """Load Hornet V4 session-continuity if hornet is installed. None otherwise."""
    # Lookup path: plugins/hornet-session-memory/state/session-graph.json
    # (or wherever hornet v1.0.0 puts it).
    for rel in (
        "plugins/hornet-session-memory/state/session-graph.json",
        "plugins/session-memory/state/session-graph.json",
    ):
        p = cwd / rel
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None
    return None


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

def __main_cli():
    """Usage:
      python pr_lifecycle.py open [--dry-run] [--base B] [--head H]
      python pr_lifecycle.py compose-desc <cluster-file>  # useful for tests
    """
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: pr_lifecycle.py (open|compose-desc) ..."}))
        sys.exit(3)

    action = sys.argv[1]
    cwd = Path.cwd()

    if action == "open":
        dry_run = "--dry-run" in sys.argv
        base = None
        head = None
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] == "--base" and i + 1 < len(args):
                base = args[i + 1]; i += 2
            elif args[i] == "--head" and i + 1 < len(args):
                head = args[i + 1]; i += 2
            else:
                i += 1
        result = open_or_update(cwd, base=base, head=head, dry_run=dry_run)
        print(json.dumps(result, indent=2))
        sys.exit(0 if not result.get("error") else 1)

    if action == "compose-desc":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "usage: compose-desc <cluster-file>"}))
            sys.exit(3)
        with open(sys.argv[2], "r", encoding="utf-8") as f:
            state = json.load(f)
        cluster = state.get("closed_clusters", [None])[-1] if state.get("closed_clusters") else None
        desc = PRDescription.from_cluster(cluster=cluster)
        print(json.dumps({"title": desc.title, "body": desc.body}, indent=2))
        sys.exit(0)

    print(json.dumps({"error": f"unknown action: {action}"}))
    sys.exit(3)


if __name__ == "__main__":
    __main_cli()
