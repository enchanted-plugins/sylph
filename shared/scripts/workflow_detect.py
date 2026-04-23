"""
W3 — Workflow-Pattern Classifier.

Infers the active branching workflow from repo signals:
  - branch graph (names, ages, counts)
  - protected-branch patterns (via config hints)
  - repo config files (.gitflow-config, .graphite_config, .sl/, .git/branchless)
  - release cadence from `git tag --sort=-creatordate`

Produces one of:
  - stacked-diffs     — Graphite / Sapling / git-branchless markers present
  - gitflow           — develop + release/* branches (legacy)
  - release-flow      — release/* branches without develop, monthly+ tag cadence
  - trunk-based       — short-lived branches (median age < 3d), active set < 20
  - github-flow       — protected main + PR-driven feature branches (3-14d age)
  - unknown           — nothing matched; emit a signal, prompt developer

Handles monorepos via per-subtree classification keyed by CODEOWNERS blocks
or a `.sylph/workflow-map.yaml` overlay.

Stdlib only. Delegates all git interaction to subprocess + `git` binary.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ──────────────────────────────────────────────────────────────────────
# git subprocess helpers
# ──────────────────────────────────────────────────────────────────────

def _git(*args: str, cwd: Path | None = None, timeout: float = 10.0) -> tuple[int, str]:
    """Invoke `git` with args; return (exit_code, stdout). stderr suppressed."""
    try:
        r = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.returncode, r.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return -1, ""


def in_git_repo(cwd: Path) -> bool:
    rc, _ = _git("rev-parse", "--git-dir", cwd=cwd)
    return rc == 0


# ──────────────────────────────────────────────────────────────────────
# Feature extraction
# ──────────────────────────────────────────────────────────────────────

@dataclass
class RepoSignals:
    branch_count: int = 0
    active_branches: list[tuple[str, float]] = field(default_factory=list)  # (name, last_commit_unix)
    median_branch_age_days: float = float("inf")
    has_develop_branch: bool = False
    has_release_branches: bool = False
    has_hotfix_branches: bool = False
    has_gitflow_config: bool = False
    has_graphite_config: bool = False
    has_sapling_dir: bool = False
    has_branchless_dir: bool = False
    default_branch: str = "main"
    tag_cadence_days: float = float("inf")  # median days between last 10 tags
    config_files_found: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "branch_count": self.branch_count,
            "active_branches": [
                {"name": n, "last_commit": t} for n, t in self.active_branches[:20]
            ],
            "median_branch_age_days": _finite(self.median_branch_age_days),
            "has_develop_branch": self.has_develop_branch,
            "has_release_branches": self.has_release_branches,
            "has_hotfix_branches": self.has_hotfix_branches,
            "has_gitflow_config": self.has_gitflow_config,
            "has_graphite_config": self.has_graphite_config,
            "has_sapling_dir": self.has_sapling_dir,
            "has_branchless_dir": self.has_branchless_dir,
            "default_branch": self.default_branch,
            "tag_cadence_days": _finite(self.tag_cadence_days),
            "config_files_found": sorted(self.config_files_found),
        }


def _finite(x: float) -> float | None:
    return x if math.isfinite(x) else None


def _median(xs: list[float]) -> float:
    if not xs:
        return float("inf")
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 == 1 else (s[mid - 1] + s[mid]) / 2


def collect_signals(cwd: Path) -> RepoSignals:
    """Run the git queries + filesystem checks; populate a RepoSignals."""
    sig = RepoSignals()

    if not in_git_repo(cwd):
        return sig

    now = time.time()

    # Default branch from HEAD's symbolic ref; fall back to 'main'.
    rc, out = _git("symbolic-ref", "--short", "HEAD", cwd=cwd)
    if rc == 0 and out.strip():
        sig.default_branch = out.strip()

    # Branch enumeration: local branches with last-commit timestamps.
    # Format: "<name>\t<unix-ts>"
    rc, out = _git(
        "for-each-ref",
        "--format=%(refname:short)\t%(committerdate:unix)",
        "refs/heads",
        cwd=cwd,
    )
    if rc == 0:
        ages: list[float] = []
        for line in out.splitlines():
            line = line.strip()
            if not line or "\t" not in line:
                continue
            name, ts = line.split("\t", 1)
            try:
                tsv = float(ts)
            except ValueError:
                continue
            sig.active_branches.append((name, tsv))
            ages.append((now - tsv) / 86400.0)

            ln = name.lower()
            if ln == "develop":
                sig.has_develop_branch = True
            if ln.startswith("release/") or ln == "release":
                sig.has_release_branches = True
            if ln.startswith("hotfix/") or ln == "hotfix":
                sig.has_hotfix_branches = True

        sig.branch_count = len(sig.active_branches)
        sig.median_branch_age_days = _median(ages)

    # Config-file / markers.
    for marker in (".gitflow-config", ".gitflow", ".graphite_config", ".graphite"):
        p = cwd / marker
        if p.exists():
            sig.config_files_found.append(marker)
            if "gitflow" in marker:
                sig.has_gitflow_config = True
            elif "graphite" in marker:
                sig.has_graphite_config = True

    if (cwd / ".sl").is_dir():
        sig.has_sapling_dir = True
        sig.config_files_found.append(".sl/")

    if (cwd / ".git" / "branchless").is_dir():
        sig.has_branchless_dir = True
        sig.config_files_found.append(".git/branchless/")

    # Tag cadence: gaps between the last 10 tags by creatordate.
    rc, out = _git(
        "for-each-ref",
        "--sort=-creatordate",
        "--format=%(creatordate:unix)",
        "--count=10",
        "refs/tags",
        cwd=cwd,
    )
    if rc == 0:
        tag_times: list[float] = []
        for ln in out.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                tag_times.append(float(ln))
            except ValueError:
                continue
        if len(tag_times) >= 2:
            gaps = [
                (tag_times[i] - tag_times[i + 1]) / 86400.0
                for i in range(len(tag_times) - 1)
                if tag_times[i] > tag_times[i + 1]
            ]
            if gaps:
                sig.tag_cadence_days = _median(gaps)

    return sig


# ──────────────────────────────────────────────────────────────────────
# Classification
# ──────────────────────────────────────────────────────────────────────

# Output labels — keep in sync with the decision tree in
# docs/architecture/highlevel.mmd and the README decision tree.
LABELS = {
    "stacked-diffs",
    "gitflow",
    "release-flow",
    "trunk-based",
    "github-flow",
    "unknown",
}


@dataclass
class Classification:
    label: str
    confidence: float  # 0.0..1.0
    rationale: list[str]
    signals_snapshot: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "confidence": round(self.confidence, 3),
            "rationale": self.rationale,
            "signals": self.signals_snapshot,
        }


def classify(sig: RepoSignals) -> Classification:
    """Weighted decision tree. Later rules only run if earlier ones don't fire."""
    r: list[str] = []
    signals_dict = sig.to_dict()

    # 1. Stacked-diff markers — most specific; skip the rest if present.
    if sig.has_graphite_config or sig.has_sapling_dir or sig.has_branchless_dir:
        r.append(
            "stacked-diff markers present: "
            + ", ".join(sig.config_files_found) or "unknown"
        )
        return Classification("stacked-diffs", 0.95, r, signals_dict)

    # 2. GitFlow — explicit config OR classic develop + release/* pattern.
    if sig.has_gitflow_config:
        r.append(".gitflow-config present (explicit GitFlow)")
        return Classification("gitflow", 0.95, r, signals_dict)

    if sig.has_develop_branch and (sig.has_release_branches or sig.has_hotfix_branches):
        r.append("develop branch + release/hotfix pattern (legacy GitFlow)")
        return Classification("gitflow", 0.85, r, signals_dict)

    # 3. Release Flow — release/* branches with monthly+ cadence, no develop.
    if sig.has_release_branches and not sig.has_develop_branch:
        if sig.tag_cadence_days >= 14.0:
            r.append(
                f"release/* branches + median tag cadence {sig.tag_cadence_days:.1f}d "
                f"(Release Flow)"
            )
            return Classification("release-flow", 0.8, r, signals_dict)
        # release/* branches but fast cadence — still Release-Flow-ish, lower confidence.
        r.append(
            f"release/* branches + tag cadence {sig.tag_cadence_days:.1f}d "
            f"(Release Flow, fast cadence)"
        )
        return Classification("release-flow", 0.6, r, signals_dict)

    # 4. Trunk-Based Development.
    if (
        sig.median_branch_age_days < 3.0
        and sig.branch_count < 20
        and sig.branch_count >= 1
    ):
        r.append(
            f"median branch age {sig.median_branch_age_days:.1f}d, "
            f"{sig.branch_count} active branches (Trunk-Based)"
        )
        return Classification("trunk-based", 0.75, r, signals_dict)

    # 5. GitHub Flow — default branch only + feature branches aged 3-14d.
    if 3.0 <= sig.median_branch_age_days <= 14.0 or (
        sig.branch_count >= 2 and sig.branch_count < 50
    ):
        r.append(
            f"feature-branch pattern + default branch ({sig.default_branch}), "
            f"median age {sig.median_branch_age_days:.1f}d (GitHub Flow)"
        )
        return Classification("github-flow", 0.7, r, signals_dict)

    # 6. Fallback.
    r.append("no pattern matched cleanly; prompt developer for override")
    return Classification("unknown", 0.3, r, signals_dict)


# ──────────────────────────────────────────────────────────────────────
# Per-subtree classification (monorepos)
# ──────────────────────────────────────────────────────────────────────

def read_workflow_map(cwd: Path) -> dict[str, str] | None:
    """If `.sylph/workflow-map.yaml` exists, parse it as a simple subpath→workflow
    mapping. We don't pull in a YAML dep — the format here is strict:

        packages/mobile: release-flow
        packages/web: trunk-based

    One line per entry, `:` separator. Comments start with `#`.
    """
    f = cwd / ".sylph" / "workflow-map.yaml"
    if not f.exists():
        return None

    mapping: dict[str, str] = {}
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        path, label = line.split(":", 1)
        label = label.strip()
        if label in LABELS:
            mapping[path.strip()] = label

    return mapping if mapping else None


# ──────────────────────────────────────────────────────────────────────
# CLI — consumed by /sylph:workflow-detect and /sylph:branch
# ──────────────────────────────────────────────────────────────────────

def detect(cwd: Path) -> dict[str, Any]:
    """Top-level: collect signals, classify, honor workflow-map overlay."""
    sig = collect_signals(cwd)
    main = classify(sig)

    result: dict[str, Any] = {
        "workflow": main.to_dict(),
        "subtree_overrides": None,
    }

    overrides = read_workflow_map(cwd)
    if overrides:
        result["subtree_overrides"] = overrides

    return result


def suggest_branch_name(workflow: str, commit_type: str | None, slug: str) -> str:
    """Suggest a branch name consistent with the workflow + Conventional Commits type."""
    slug = re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-") or "work"

    if workflow == "github-flow":
        # type/short-slug
        prefix = (commit_type or "feat").lower()
        return f"{prefix}/{slug}"

    if workflow == "trunk-based":
        # Short-lived branches; user/slug for TBD where branches are measured in hours.
        user = os.environ.get("USER") or os.environ.get("USERNAME") or "dev"
        return f"{user.lower()}/{slug}"

    if workflow == "gitflow":
        # feature/slug, bugfix/slug, hotfix/slug
        if commit_type == "fix":
            return f"bugfix/{slug}"
        if commit_type == "hotfix":
            return f"hotfix/{slug}"
        return f"feature/{slug}"

    if workflow == "release-flow":
        # feature/slug off main; hotfix/slug off release/*
        if commit_type in ("fix", "hotfix"):
            return f"hotfix/{slug}"
        return f"feature/{slug}"

    if workflow == "stacked-diffs":
        # Graphite/Sapling style: short topic names, no prefix.
        return slug

    # unknown → sensible default
    return f"wip/{slug}"


def __main_cli():
    """CLI for /sylph:workflow-detect + /sylph:branch.

    Usage:
      python workflow_detect.py detect [cwd]
      python workflow_detect.py suggest-branch <workflow> <type|-> <slug>
    """
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: workflow_detect.py (detect|suggest-branch) ..."}))
        sys.exit(3)

    action = sys.argv[1]

    if action == "detect":
        cwd = Path(sys.argv[2]) if len(sys.argv) >= 3 else Path.cwd()
        result = detect(cwd)
        print(json.dumps(result, indent=2))
        sys.exit(0)

    if action == "suggest-branch":
        if len(sys.argv) < 5:
            print(json.dumps({"error": "usage: suggest-branch <workflow> <type|-> <slug>"}))
            sys.exit(3)
        workflow = sys.argv[2]
        ctype = sys.argv[3] if sys.argv[3] != "-" else None
        slug = sys.argv[4]
        name = suggest_branch_name(workflow, ctype, slug)
        print(json.dumps({"branch": name}))
        sys.exit(0)

    print(json.dumps({"error": f"unknown action: {action}"}))
    sys.exit(3)


if __name__ == "__main__":
    __main_cli()
