"""
W5 — Gauss Learning (Weaver).

Per-developer preference persistence via exponential moving averages
with Allay-A4 atomic serialization. Tracks:

  - commit_style: dict of signals
      - scope_usage_rate            float in [0,1]  — fraction of commits with (scope)
      - body_present_rate           float in [0,1]  — fraction of commits with a body
      - avg_subject_length          float           — char length of subject line
      - top_scopes                  list[(scope, weight)]  — seen scope frequencies
      - type_frequencies            dict[type, float]

  - branch_naming:
      - slug_style                  'kebab' | 'snake' | 'mixed'
      - type_prefix_rate            float in [0,1]  — e.g. feat/foo vs bare names
      - user_prefix_rate            float in [0,1]  — TBD-style user/foo

  - pr_turnaround:
      - median_hours_to_first_review  float
      - median_hours_to_merge         float

  - reviewer_overrides:
      - manually_added_handles: dict[handle, weight]  — developer's reviewer
                                                         corrections over W4 suggestions

  - w2_corrections:
      - boundary_overrides: int  — times developer merged/split vs W2 decision

EMA update: `new = alpha * signal + (1 - alpha) * old` with alpha from
WEAVER_GAUSS_ALPHA (0.3 default). Bootstrap floor at
WEAVER_GAUSS_BOOTSTRAP_MIN_SAMPLES — below the floor, confidence is low
and Weaver ignores the learned priors.

Stdlib only.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


DEFAULT_ALPHA = 0.3
DEFAULT_BOOTSTRAP_MIN_SAMPLES = 10
STATE_VERSION = 1


# ──────────────────────────────────────────────────────────────────────
# State model
# ──────────────────────────────────────────────────────────────────────

def _empty_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "updated_at": None,
        "sample_count": 0,
        "commit_style": {
            "scope_usage_rate": 0.0,
            "body_present_rate": 0.0,
            "avg_subject_length": 0.0,
            "type_frequencies": {},
            "top_scopes": {},
        },
        "branch_naming": {
            "slug_style": "unknown",   # 'kebab' | 'snake' | 'mixed' | 'unknown'
            "type_prefix_rate": 0.0,
            "user_prefix_rate": 0.0,
        },
        "pr_turnaround": {
            "median_hours_to_first_review": None,
            "median_hours_to_merge": None,
        },
        "reviewer_overrides": {},      # handle -> weight
        "w2_corrections": {
            "boundary_overrides": 0,
            "false_merge": 0,           # developer merged clusters W2 split
            "false_split": 0,           # developer split a cluster W2 kept
        },
    }


# ──────────────────────────────────────────────────────────────────────
# EMA helpers
# ──────────────────────────────────────────────────────────────────────

def ema(old: float, signal: float, alpha: float = DEFAULT_ALPHA) -> float:
    return alpha * signal + (1.0 - alpha) * old


def ema_dict(old: dict[str, float], signal: dict[str, float], alpha: float = DEFAULT_ALPHA) -> dict[str, float]:
    """EMA over a dict of scalars. Keys present in either side are tracked."""
    keys = set(old) | set(signal)
    return {k: ema(old.get(k, 0.0), signal.get(k, 0.0), alpha) for k in keys}


# ──────────────────────────────────────────────────────────────────────
# Update entry points — called from the events hook or post-commit flow
# ──────────────────────────────────────────────────────────────────────

def record_commit(
    state: dict[str, Any],
    *,
    type_: str,
    scope: str | None,
    breaking: bool,
    subject: str,
    body: str,
    alpha: float = DEFAULT_ALPHA,
) -> dict[str, Any]:
    """Absorb one commit into the moving averages."""
    cs = state["commit_style"]
    cs["scope_usage_rate"] = ema(cs["scope_usage_rate"], 1.0 if scope else 0.0, alpha)
    cs["body_present_rate"] = ema(cs["body_present_rate"], 1.0 if body.strip() else 0.0, alpha)
    cs["avg_subject_length"] = ema(cs["avg_subject_length"], float(len(subject)), alpha)

    cs["type_frequencies"] = ema_dict(
        cs.get("type_frequencies") or {},
        {type_: 1.0},
        alpha,
    )

    if scope:
        cs["top_scopes"] = ema_dict(
            cs.get("top_scopes") or {},
            {scope: 1.0},
            alpha,
        )

    state["sample_count"] = int(state.get("sample_count", 0)) + 1
    state["updated_at"] = time.time()
    return state


def record_branch_name(state: dict[str, Any], name: str, alpha: float = DEFAULT_ALPHA) -> dict[str, Any]:
    """Absorb one branch name choice into the moving averages."""
    bn = state["branch_naming"]
    slug = name.split("/")[-1] if "/" in name else name

    # slug style
    if "-" in slug and "_" not in slug:
        style_signal = "kebab"
    elif "_" in slug and "-" not in slug:
        style_signal = "snake"
    else:
        style_signal = "mixed"
    # Store last-seen style; EMA over styles is awkward so we just take the
    # majority-of-last-10 via a rolling list if we cared. Simpler: overwrite.
    bn["slug_style"] = style_signal

    # prefix signals
    has_type_prefix = "/" in name and name.split("/", 1)[0] in (
        "feat", "feature", "fix", "bugfix", "hotfix", "chore", "docs", "refactor"
    )
    has_user_prefix = "/" in name and not has_type_prefix

    bn["type_prefix_rate"] = ema(bn["type_prefix_rate"], 1.0 if has_type_prefix else 0.0, alpha)
    bn["user_prefix_rate"] = ema(bn["user_prefix_rate"], 1.0 if has_user_prefix else 0.0, alpha)

    state["updated_at"] = time.time()
    return state


def record_reviewer_override(
    state: dict[str, Any],
    handle: str,
    added: bool,
    alpha: float = DEFAULT_ALPHA,
) -> dict[str, Any]:
    """Developer added (or removed) a reviewer that W4 didn't suggest."""
    overrides = state["reviewer_overrides"]
    signal = 1.0 if added else -1.0
    overrides[handle] = ema(overrides.get(handle, 0.0), signal, alpha)
    state["updated_at"] = time.time()
    return state


def record_w2_correction(
    state: dict[str, Any],
    correction: str,  # 'merge' (W2 split wrongly) | 'split' (W2 merged wrongly)
) -> dict[str, Any]:
    c = state["w2_corrections"]
    c["boundary_overrides"] = int(c.get("boundary_overrides", 0)) + 1
    if correction == "merge":
        c["false_split"] = int(c.get("false_split", 0)) + 1
    elif correction == "split":
        c["false_merge"] = int(c.get("false_merge", 0)) + 1
    state["updated_at"] = time.time()
    return state


# ──────────────────────────────────────────────────────────────────────
# Priors: what do we tell the downstream engines?
# ──────────────────────────────────────────────────────────────────────

def has_confidence(state: dict[str, Any], min_samples: int = DEFAULT_BOOTSTRAP_MIN_SAMPLES) -> bool:
    """True when sample_count exceeds the bootstrap threshold."""
    return int(state.get("sample_count", 0)) >= min_samples


def priors(state: dict[str, Any]) -> dict[str, Any]:
    """Serialize the learned signals in a form other engines can consume.

    When confidence is low (sample_count < bootstrap), prior values are
    returned but flagged with `confident: false` so consumers use defaults."""
    confident = has_confidence(state)
    return {
        "confident": confident,
        "sample_count": int(state.get("sample_count", 0)),
        "commit_style": dict(state.get("commit_style", {})),
        "branch_naming": dict(state.get("branch_naming", {})),
        "pr_turnaround": dict(state.get("pr_turnaround", {})),
        "reviewer_overrides": dict(state.get("reviewer_overrides", {})),
        "w2_corrections": dict(state.get("w2_corrections", {})),
    }


# ──────────────────────────────────────────────────────────────────────
# Persistence (Allay-A4)
# ──────────────────────────────────────────────────────────────────────

def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _empty_state()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _empty_state()

    # Schema migration hook — today's only version is 1.
    version = raw.get("version", 0)
    if version != STATE_VERSION:
        # Future: migrate. For now, reset on mismatch.
        return _empty_state()

    # Fill any missing sections from the empty template so callers can
    # trust the shape.
    empty = _empty_state()
    for k, default in empty.items():
        raw.setdefault(k, default)
    return raw


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=str(path.parent),
        prefix=f".{path.name}.", suffix=".tmp", delete=False,
    ) as tmp:
        json.dump(state, tmp, indent=2, sort_keys=True)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_name = tmp.name
    os.replace(tmp_name, path)


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

def __main_cli():
    """Usage:
      python gauss_learning.py priors <state-path>
      python gauss_learning.py record-commit <state-path>   (reads JSON on stdin)
      python gauss_learning.py record-branch <state-path> <branch-name>
      python gauss_learning.py record-reviewer <state-path> <handle> (added|removed)
      python gauss_learning.py record-w2-correction <state-path> (merge|split)
      python gauss_learning.py dump <state-path>
    """
    if len(sys.argv) < 3:
        print(json.dumps({"error": "usage: gauss_learning.py <action> <state-path> ..."}))
        sys.exit(3)

    action = sys.argv[1]
    state_path = Path(sys.argv[2])

    state = load_state(state_path)

    if action == "priors":
        print(json.dumps(priors(state), indent=2))
        sys.exit(0)

    if action == "dump":
        print(json.dumps(state, indent=2, sort_keys=True))
        sys.exit(0)

    if action == "record-commit":
        raw = sys.stdin.read()
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            print(json.dumps({"error": "invalid JSON on stdin"}))
            sys.exit(3)
        state = record_commit(
            state,
            type_=str(payload.get("type") or ""),
            scope=payload.get("scope"),
            breaking=bool(payload.get("breaking")),
            subject=str(payload.get("subject") or ""),
            body=str(payload.get("body") or ""),
        )
        save_state(state_path, state)
        print(json.dumps({"updated": True, "sample_count": state["sample_count"]}))
        sys.exit(0)

    if action == "record-branch":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "usage: record-branch <state> <name>"}))
            sys.exit(3)
        state = record_branch_name(state, sys.argv[3])
        save_state(state_path, state)
        print(json.dumps({"updated": True}))
        sys.exit(0)

    if action == "record-reviewer":
        if len(sys.argv) < 5:
            print(json.dumps({"error": "usage: record-reviewer <state> <handle> (added|removed)"}))
            sys.exit(3)
        handle = sys.argv[3]
        added = sys.argv[4].lower() == "added"
        state = record_reviewer_override(state, handle, added)
        save_state(state_path, state)
        print(json.dumps({"updated": True}))
        sys.exit(0)

    if action == "record-w2-correction":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "usage: record-w2-correction <state> (merge|split)"}))
            sys.exit(3)
        correction = sys.argv[3]
        state = record_w2_correction(state, correction)
        save_state(state_path, state)
        print(json.dumps({"updated": True}))
        sys.exit(0)

    print(json.dumps({"error": f"unknown action: {action}"}))
    sys.exit(3)


if __name__ == "__main__":
    __main_cli()
