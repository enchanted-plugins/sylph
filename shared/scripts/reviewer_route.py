"""
W4 — Path-History Reviewer Routing.

For each changed file in a PR, build a blame-graph score for candidate
reviewers weighted by:
  - recency (90-day half-life on last-commit timestamp)
  - path-depth specificity (authors of deep paths rank higher than those
    touching root-level dirs only)
  - CODEOWNERS membership (union, not replace — CODEOWNERS entries get
    a hard boost but don't crowd out blame-graph suggestions)
  - availability signal (optional — from hornet.reviewer.availability.changed
    events; when absent, assume all candidates are available)

Output: top-K reviewer logins, capped at WEAVER_REVIEWER_MAX_SUGGEST (3).

Stdlib only. Delegates all git interaction to `git log`.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_HALF_LIFE_DAYS = 90.0
DEFAULT_MAX_SUGGEST = 3


# ──────────────────────────────────────────────────────────────────────
# git blame via `git log`
# ──────────────────────────────────────────────────────────────────────

def _git_log_authors(path: str, cwd: Path, limit: int = 50) -> list[tuple[str, str, float]]:
    """Return [(name, email, unix_ts), ...] for the last N commits touching path."""
    try:
        r = subprocess.run(
            [
                "git", "log",
                f"--format=%an%x09%ae%x09%at",
                f"-n{limit}",
                "--", path,
            ],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if r.returncode != 0:
        return []

    out: list[tuple[str, str, float]] = []
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            try:
                ts = float(parts[2])
            except ValueError:
                continue
            out.append((parts[0], parts[1], ts))
    return out


# ──────────────────────────────────────────────────────────────────────
# CODEOWNERS parsing
# ──────────────────────────────────────────────────────────────────────

CODEOWNERS_PATHS = [
    ".github/CODEOWNERS",
    "CODEOWNERS",
    "docs/CODEOWNERS",
]


def _read_codeowners(cwd: Path) -> list[tuple[str, list[str]]]:
    """Parse CODEOWNERS. Returns [(glob, [owners]), ...]."""
    for rel in CODEOWNERS_PATHS:
        p = cwd / rel
        if p.exists():
            return _parse_codeowners_lines(p.read_text(encoding="utf-8").splitlines())
    return []


def _parse_codeowners_lines(lines: list[str]) -> list[tuple[str, list[str]]]:
    entries: list[tuple[str, list[str]]] = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) < 2:
            continue
        glob = parts[0]
        owners = [p.lstrip("@") for p in parts[1:] if p.startswith("@")]
        if owners:
            entries.append((glob, owners))
    return entries


def _glob_match(path: str, glob: str) -> bool:
    """GitHub CODEOWNERS glob semantics (subset).

    - `*` matches any path segment content (not /)
    - `**` matches any number of path segments
    - leading `/` means root-anchored
    - trailing `/` means directory + everything under it
    """
    pat = glob
    anchored = pat.startswith("/")
    if anchored:
        pat = pat[1:]

    # Expand trailing / to match everything under the directory.
    if pat.endswith("/"):
        pat = pat + "**"

    # Escape regex-meaningful chars except * and ?.
    def esc(ch: str) -> str:
        if ch in ".^$+(){}|\\":
            return "\\" + ch
        return ch

    # Build the regex.
    i = 0
    buf = []
    while i < len(pat):
        c = pat[i]
        if c == "*":
            if i + 1 < len(pat) and pat[i + 1] == "*":
                # **
                buf.append(".*")
                i += 2
                # Consume an optional trailing /
                if i < len(pat) and pat[i] == "/":
                    i += 1
            else:
                buf.append("[^/]*")
                i += 1
        elif c == "?":
            buf.append("[^/]")
            i += 1
        else:
            buf.append(esc(c))
            i += 1

    regex = "".join(buf)
    if anchored:
        return bool(re.match(f"^{regex}$", path))
    # Non-anchored: match anywhere in the path.
    return bool(re.search(regex, path))


def _codeowners_for_path(path: str, entries: list[tuple[str, list[str]]]) -> list[str]:
    """Return owners for a path. Last matching entry wins (CODEOWNERS semantics)."""
    winner: list[str] | None = None
    for glob, owners in entries:
        if _glob_match(path, glob):
            winner = owners
    return winner or []


# ──────────────────────────────────────────────────────────────────────
# Scoring
# ──────────────────────────────────────────────────────────────────────

@dataclass
class Candidate:
    identity: str            # "@login" if known, else "Name <email>"
    blame_score: float = 0.0
    codeowners_paths: list[str] = field(default_factory=list)
    availability: float = 1.0  # 0.0..1.0; 1.0 = fully available

    @property
    def total_score(self) -> float:
        owner_boost = 1.5 if self.codeowners_paths else 1.0
        return self.blame_score * owner_boost * self.availability


def _path_depth_weight(path: str) -> float:
    """Deeper paths → higher weight; max ~1.5."""
    depth = path.count("/")
    return 1.0 + min(0.5, depth * 0.1)


def _recency_weight(ts: float, now: float, half_life_days: float) -> float:
    """Exponential decay: age * ln(2) / half_life."""
    age_days = max(0.0, (now - ts) / 86400.0)
    return math.exp(-age_days * math.log(2) / half_life_days)


def score_reviewers(
    changed_paths: list[str],
    cwd: Path,
    availability: dict[str, float] | None = None,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    exclude: set[str] | None = None,
    now: float | None = None,
) -> list[Candidate]:
    """Score all candidate reviewers across all changed files.

    Returns a sorted list descending by total_score.
    """
    now = now if now is not None else time.time()
    availability = availability or {}
    exclude = exclude or set()

    codeowner_entries = _read_codeowners(cwd)

    # identity_key -> Candidate
    cands: dict[str, Candidate] = {}

    for path in changed_paths:
        depth_w = _path_depth_weight(path)

        # Blame graph from git log
        for name, email, ts in _git_log_authors(path, cwd):
            identity = f"{name} <{email}>"
            if identity in exclude:
                continue
            c = cands.setdefault(identity, Candidate(identity=identity))
            c.blame_score += _recency_weight(ts, now, half_life_days) * depth_w

        # CODEOWNERS matches
        owners = _codeowners_for_path(path, codeowner_entries)
        for owner in owners:
            handle = f"@{owner}"
            if handle in exclude:
                continue
            c = cands.setdefault(handle, Candidate(identity=handle))
            c.codeowners_paths.append(path)

    # Attach availability
    for ident, c in cands.items():
        # Try matching @handle first, then by email.
        c.availability = availability.get(ident, c.availability)

    ranked = sorted(cands.values(), key=lambda x: x.total_score, reverse=True)
    return ranked


def suggest(
    changed_paths: list[str],
    cwd: Path,
    *,
    max_suggest: int = DEFAULT_MAX_SUGGEST,
    availability: dict[str, float] | None = None,
    exclude: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Convenience: top-K reviewers as a list of dicts ready for the hook."""
    ranked = score_reviewers(changed_paths, cwd, availability=availability, exclude=exclude)
    return [
        {
            "identity": c.identity,
            "score": round(c.total_score, 3),
            "blame_score": round(c.blame_score, 3),
            "codeowners": c.codeowners_paths,
            "availability": c.availability,
        }
        for c in ranked[:max_suggest]
    ]


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

def __main_cli():
    """Usage:
      python reviewer_route.py <cwd> <max> <path1> <path2> ...
    """
    if len(sys.argv) < 3:
        print(json.dumps({"error": "usage: reviewer_route.py <cwd> <max> <path...>"}))
        sys.exit(3)

    cwd = Path(sys.argv[1])
    try:
        max_k = int(sys.argv[2])
    except ValueError:
        max_k = DEFAULT_MAX_SUGGEST

    paths = sys.argv[3:]
    if not paths:
        print(json.dumps([]))
        sys.exit(0)

    out = suggest(paths, cwd, max_suggest=max_k)
    print(json.dumps(out, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    __main_cli()
