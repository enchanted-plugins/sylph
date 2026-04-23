#!/usr/bin/env python3
"""Sylph observability rollup — aggregates per-plugin metrics.jsonl feeds.

Every hook and script across Sylph appends JSONL records to its plugin's
``state/metrics.jsonl``. This script is the single reader surface that turns
that raw event stream into a session/day/week rollup for ``/sylph:stats``.

Contract:
    python stats.py [--period session|day|week|all] [--json] [--since YYYY-MM-DD]

Stdlib only — no pandas, no rich. Missing files are treated as empty
(no counts, not an error), so the tool works the moment Sylph is installed
even before any hook has fired.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable


# ── Paths ──────────────────────────────────────────────────────────────
# Resolve repo root relative to this file: shared/scripts/stats.py → ../..
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_root(explicit: str | None) -> Path:
    """Allow tests to pass SYLPH_REPO_ROOT env / --root override."""
    import os

    if explicit:
        return Path(explicit).resolve()
    env = os.environ.get("SYLPH_REPO_ROOT")
    if env:
        return Path(env).resolve()
    return REPO_ROOT


# ── JSONL reader ───────────────────────────────────────────────────────

def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file; missing file → []. Malformed lines are skipped."""
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
    except OSError:
        return []
    return out


def _parse_ts(rec: dict[str, Any]) -> datetime | None:
    """Best-effort ts parser — supports ISO-8601 and epoch seconds/ms."""
    ts = rec.get("ts")
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        # Heuristic: > 10^12 ≈ ms
        if ts > 1e12:
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(ts, str):
        # Accept trailing Z
        s = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    return None


# ── Period resolution ──────────────────────────────────────────────────

def _session_start(root: Path) -> datetime:
    """Best-effort session-start timestamp.

    Look at the newest file under ``capability-memory/state/session-cache/``;
    fall back to "now - 2h" when the cache is empty or missing. The 2h window
    matches the pragmatic fallback specified in the CLI contract.
    """
    cache_dir = root / "plugins" / "capability-memory" / "state" / "session-cache"
    now = datetime.now(tz=timezone.utc)
    fallback = now - timedelta(hours=2)
    if not cache_dir.is_dir():
        return fallback
    newest = fallback
    try:
        for entry in cache_dir.iterdir():
            try:
                mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            if mtime > newest:
                newest = mtime
    except OSError:
        return fallback
    return newest


def _resolve_window(period: str, since: str | None, root: Path) -> tuple[datetime, datetime]:
    """Return (start, end) UTC datetimes for the requested period."""
    now = datetime.now(tz=timezone.utc)
    if since:
        try:
            start = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return start, now
        except ValueError as exc:
            raise SystemExit(f"--since expects YYYY-MM-DD (got {since!r}): {exc}")
    if period == "session":
        return _session_start(root), now
    if period == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now
    if period == "week":
        return now - timedelta(days=7), now
    if period == "all":
        return datetime.fromtimestamp(0, tz=timezone.utc), now
    raise SystemExit(f"unknown --period {period!r}")


def _in_window(rec: dict[str, Any], start: datetime, end: datetime) -> bool:
    ts = _parse_ts(rec)
    if ts is None:
        # No timestamp → include only for the "all" window (start == epoch).
        return start.timestamp() == 0
    return start <= ts <= end


# ── Count pending inboxes ──────────────────────────────────────────────

def _count_pending(path: Path) -> int:
    """Count records with executed=False in a pending-action JSONL inbox."""
    n = 0
    for rec in _read_jsonl(path):
        # Absent or explicit-false both count as pending — matches the
        # convention used by branch-workflow / commit-intelligence / pr-lifecycle.
        if not rec.get("executed", False):
            n += 1
    return n


# ── Gate decisions ─────────────────────────────────────────────────────

def _categorise_gate(rec: dict[str, Any]) -> tuple[str, str]:
    """Return (decision, category) from a sylph-gate audit record.

    Accepts a few field shapes gracefully: decision|outcome|action, and
    category|pattern|operation. Unknown → ("other", "unknown").
    """
    decision = (
        rec.get("decision")
        or rec.get("outcome")
        or rec.get("action")
        or "other"
    )
    category = (
        rec.get("category")
        or rec.get("pattern")
        or rec.get("operation")
        or "unknown"
    )
    return str(decision), str(category)


# ── Aggregation ────────────────────────────────────────────────────────

def _safe_mean(values: Iterable[float]) -> float | None:
    vals = [v for v in values if isinstance(v, (int, float))]
    if not vals:
        return None
    return float(fmean(vals))


def build_rollup(root: Path, start: datetime, end: datetime) -> dict[str, Any]:
    """Aggregate every metrics source into a single rollup dict."""
    # Boundary segmenter
    bs_path = root / "plugins" / "boundary-segmenter" / "state" / "metrics.jsonl"
    bs_records = [r for r in _read_jsonl(bs_path) if _in_window(r, start, end)]
    boundaries = [r for r in bs_records if r.get("boundary") is True]
    uncertain = [r for r in boundaries if r.get("uncertain") is True]
    distances = [r.get("distance") for r in boundaries]
    avg_distance = _safe_mean(distances)

    # Branch-workflow
    bw_path = root / "plugins" / "branch-workflow" / "state" / "metrics.jsonl"
    bw_records = [r for r in _read_jsonl(bw_path) if _in_window(r, start, end)]
    workflow_counts = Counter(
        r.get("workflow", "unknown") for r in bw_records
        if r.get("event") == "w3.boundary.observed"
    )
    w3_confidences = [
        r.get("confidence") for r in bw_records
        if r.get("event") == "w3.boundary.observed"
    ]

    # Commit-intelligence
    ci_path = root / "plugins" / "commit-intelligence" / "state" / "metrics.jsonl"
    ci_records = [r for r in _read_jsonl(ci_path) if _in_window(r, start, end)]
    commit_types = Counter(
        r.get("suggested_type", "unknown") for r in ci_records
        if r.get("event") == "w1.boundary.observed"
    )

    # Sylph-gate audit
    gate_path = root / "plugins" / "sylph-gate" / "state" / "audit.jsonl"
    gate_records = [r for r in _read_jsonl(gate_path) if _in_window(r, start, end)]
    gate_decisions: Counter[str] = Counter()
    gate_blocked_categories: Counter[str] = Counter()
    for r in gate_records:
        decision, category = _categorise_gate(r)
        gate_decisions[decision] += 1
        if decision in ("blocked", "block", "deny", "denied"):
            gate_blocked_categories[category] += 1

    # Pending inboxes (snapshot, independent of the time window)
    pending_actions = _count_pending(
        root / "plugins" / "branch-workflow" / "state" / "pending-actions.jsonl"
    )
    pending_drafts = _count_pending(
        root / "plugins" / "commit-intelligence" / "state" / "pending-drafts.jsonl"
    )
    pending_prs = _count_pending(
        root / "plugins" / "pr-lifecycle" / "state" / "pending-prs.jsonl"
    )

    # Top files by edit churn (from boundary-segmenter post_tool_use records,
    # which carry a `path` when the event was an edit).
    file_churn: Counter[str] = Counter()
    for r in bs_records:
        p = r.get("path") or r.get("file")
        if p:
            file_churn[str(p)] += 1

    # Learning state — pull sample_count + confident flag if present.
    learnings_path = root / "plugins" / "sylph-learning" / "state" / "learnings.json"
    learning_summary: dict[str, Any] = {}
    if learnings_path.is_file():
        try:
            data = json.loads(learnings_path.read_text(encoding="utf-8"))
            learning_summary = {
                "sample_count": data.get("sample_count", 0),
                "confident": bool(data.get("confident", False)),
                "schema_version": data.get("schema_version"),
            }
        except (OSError, json.JSONDecodeError):
            learning_summary = {}

    return {
        "window": {
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        "boundaries_detected": len(boundaries),
        "boundaries_uncertain": len(uncertain),
        "boundary_avg_distance": avg_distance,
        "branches_suggested": sum(workflow_counts.values()),
        "branch_workflows": dict(workflow_counts),
        "branch_avg_confidence": _safe_mean(w3_confidences),
        "commits_drafted": sum(commit_types.values()),
        "commit_types": dict(commit_types),
        "prs_drafted": 0,  # pr-lifecycle emits via event bus, not metrics.jsonl yet
        "gate_decisions_total": sum(gate_decisions.values()),
        "gate_decisions": dict(gate_decisions),
        "gate_blocked_categories": dict(gate_blocked_categories),
        "pending_actions": pending_actions,
        "pending_drafts": pending_drafts,
        "pending_prs": pending_prs,
        "top_file_churn": file_churn.most_common(5),
        "learning": learning_summary,
    }


# ── Human formatter ────────────────────────────────────────────────────

def _fmt_counts(counter: dict[str, int]) -> str:
    if not counter:
        return "—"
    items = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return ", ".join(f"{k} × {v}" for k, v in items)


def _fmt_local(dt_iso: str) -> str:
    try:
        dt = datetime.fromisoformat(dt_iso)
    except ValueError:
        return dt_iso
    return dt.strftime("%Y-%m-%d %H:%M")


def render_human(rollup: dict[str, Any], period: str) -> str:
    window = rollup["window"]
    header = (
        f"Sylph — {period} stats "
        f"({_fmt_local(window['start'])} → {_fmt_local(window['end'])})"
    )
    rule = "─" * max(len(header), 49)
    lines = [header, rule]

    # Boundaries
    b_count = rollup["boundaries_detected"]
    b_uncertain = rollup["boundaries_uncertain"]
    b_dist = rollup["boundary_avg_distance"]
    if b_count:
        extra = []
        if b_dist is not None:
            extra.append(f"W2 avg distance: {b_dist:.2f}")
        if b_uncertain:
            extra.append(f"{b_uncertain} routed to Opus judgment")
        tail = f"   ({', '.join(extra)})" if extra else ""
    else:
        tail = ""
    lines.append(f"{'Boundaries detected:':<24}{b_count:>4}{tail}")

    # Branches
    br_count = rollup["branches_suggested"]
    wf = rollup["branch_workflows"]
    tail = ""
    if br_count and wf:
        tail = f"   ({len(wf)} workflows: {_fmt_counts(wf)})"
    lines.append(f"{'Branches suggested:':<24}{br_count:>4}{tail}")

    # Commits
    c_count = rollup["commits_drafted"]
    ct = rollup["commit_types"]
    tail = f"   ({_fmt_counts(ct)})" if c_count and ct else ""
    lines.append(f"{'Commits drafted:':<24}{c_count:>4}{tail}")

    # PRs
    lines.append(f"{'PRs drafted:':<24}{rollup['prs_drafted']:>4}")

    # Gate decisions — highlight blocks.
    blocked = sum(rollup["gate_blocked_categories"].values())
    cats = rollup["gate_blocked_categories"]
    if blocked:
        tail = f" blocked ({_fmt_counts(cats)})"
        lines.append(f"{'Gate decisions:':<24}{blocked:>4}{tail}")
    else:
        total = rollup["gate_decisions_total"]
        lines.append(f"{'Gate decisions:':<24}{total:>4}   (0 blocked)")

    # Pending
    lines.append(
        f"{'Pending inbox:':<24}{'':>4}   "
        f"{rollup['pending_actions']} actions, "
        f"{rollup['pending_drafts']} drafts, "
        f"{rollup['pending_prs']} PRs"
    )

    # Top churn
    churn = rollup["top_file_churn"]
    if churn:
        lines.append("")
        churn_str = ", ".join(f"{p} ({n})" for p, n in churn)
        lines.append(f"Top files by edit churn: {churn_str}")

    # Learning
    learning = rollup.get("learning") or {}
    if learning.get("sample_count"):
        lines.append("")
        conf = "confident" if learning.get("confident") else "bootstrapping"
        lines.append(
            f"W5 learning: {learning['sample_count']} samples ({conf})"
        )

    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sylph-stats",
        description="Rollup observability stats across every Sylph plugin.",
    )
    p.add_argument(
        "--period",
        choices=("session", "day", "week", "all"),
        default="session",
        help="time window (default: session)",
    )
    p.add_argument(
        "--since",
        help="explicit start date, YYYY-MM-DD (overrides --period)",
    )
    p.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="emit structured JSON instead of the human-readable table",
    )
    p.add_argument(
        "--root",
        help="override repo root (testing). Falls back to SYLPH_REPO_ROOT env.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    root = _resolve_root(args.root)
    start, end = _resolve_window(args.period, args.since, root)
    rollup = build_rollup(root, start, end)

    # Windows default console is cp1252; box-drawing + arrows need UTF-8.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    if args.as_json:
        print(json.dumps(rollup, indent=2, sort_keys=True))
    else:
        print(render_human(rollup, args.period if not args.since else "since"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
