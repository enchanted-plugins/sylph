#!/usr/bin/env python3
"""
audit_query.py — read, filter, and render Sylph's destructive-op audit log.

Audit records are appended to plugins/sylph-gate/state/audit.jsonl by the
sylph-gate PreToolUse(Bash) hook. Each line is a JSON object. Known fields:

    ts              ISO-8601 UTC, e.g. "2026-04-15T09:22:17Z"
    op              short op name or command, e.g. "git push --force"
    cmd             raw command string (may be absent in older / spec'd records)
    pattern         the matched destructive-op pattern id (spec'd — may be absent)
    argv            argv array (spec'd — may be absent)
    head_sha        HEAD sha at time of decision (spec'd — may be absent)
    rationale       human-readable explanation (spec'd — may be absent)
    verdict_exit    0 safe, 1 destructive, 2 protected-destructive
    recovery_days   recovery-window days the classifier reported
    bypass          present iff the developer used --yes-i-know (or similar)

This tool is consumer-only. It never writes to audit.jsonl, and it never
second-guesses the producer: missing fields degrade gracefully, malformed
lines are skipped with a stderr warning.

Zero runtime deps beyond Python 3.8+ stdlib.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator


# ── Path resolution ────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent  # shared/scripts/ → repo root
DEFAULT_AUDIT = REPO_ROOT / "plugins" / "sylph-gate" / "state" / "audit.jsonl"


# ── Record helpers ─────────────────────────────────────────────────────

def _parse_ts(value: str) -> datetime | None:
    """Parse an ISO-8601 ts field. Tolerates trailing 'Z' and missing tz."""
    if not value:
        return None
    try:
        # Normalize trailing Z → +00:00 for fromisoformat().
        s = value.replace("Z", "+00:00") if value.endswith("Z") else value
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _parse_date_bound(value: str, *, end_of_day: bool) -> datetime:
    """Parse YYYY-MM-DD. end_of_day=True → 23:59:59.999999 UTC inclusive."""
    try:
        d = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise SystemExit(f"audit_query: invalid date '{value}' (expected YYYY-MM-DD)") from exc
    if end_of_day:
        d = d.replace(hour=23, minute=59, second=59, microsecond=999999)
    return d.replace(tzinfo=timezone.utc)


def _decision(rec: dict) -> str:
    """Normalize to {blocked, allowed, bypassed}.

    bypassed = any truthy `bypass` field present
    allowed  = verdict_exit == 0
    blocked  = otherwise
    """
    if rec.get("bypass"):
        return "bypassed"
    try:
        if int(rec.get("verdict_exit", 0)) == 0:
            return "allowed"
    except (TypeError, ValueError):
        pass
    return "blocked"


# ── IO ─────────────────────────────────────────────────────────────────

def _iter_records(path: Path) -> Iterator[dict]:
    """Yield parsed records from audit.jsonl, skipping malformed lines."""
    with path.open("r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                print(
                    f"audit_query: skipping malformed line {lineno}: {exc}",
                    file=sys.stderr,
                )
                continue
            if not isinstance(rec, dict):
                print(
                    f"audit_query: skipping line {lineno}: not a JSON object",
                    file=sys.stderr,
                )
                continue
            yield rec


# ── Filter pipeline ────────────────────────────────────────────────────

def _apply_filters(
    records: Iterable[dict],
    *,
    since: datetime | None,
    until: datetime | None,
    pattern: str | None,
    verdict: str | None,
) -> list[dict]:
    out: list[dict] = []
    for rec in records:
        if since or until:
            ts = _parse_ts(rec.get("ts", ""))
            if ts is None:
                # No parseable ts → only include if no date filter.
                continue
            if since and ts < since:
                continue
            if until and ts > until:
                continue
        if pattern is not None and rec.get("pattern") != pattern:
            continue
        if verdict is not None and _decision(rec) != verdict:
            continue
        out.append(rec)
    return out


# ── Rendering ──────────────────────────────────────────────────────────

def _short(value: str, width: int) -> str:
    if len(value) <= width:
        return value.ljust(width)
    return value[: max(0, width - 1)] + "…"


def _render_human(records: list[dict], *, since: datetime | None, until: datetime | None) -> str:
    if not records:
        return "no audit entries match."

    # Header window label.
    if since and until:
        window = f"between {since:%Y-%m-%d} and {until:%Y-%m-%d}"
    elif since:
        window = f"since {since:%Y-%m-%d}"
    elif until:
        window = f"through {until:%Y-%m-%d}"
    else:
        window = "(all time)"

    lines = [
        f"Sylph audit — {len(records)} decision{'s' if len(records) != 1 else ''} {window}",
        "─" * 69,
        f"{'ts (UTC)':<20} {'pattern':<24} {'verdict':<10} op",
    ]
    for rec in records:
        ts_raw = rec.get("ts", "")
        dt = _parse_ts(ts_raw)
        ts_disp = dt.strftime("%Y-%m-%d %H:%M") if dt else ts_raw[:16]
        pattern = rec.get("pattern") or "-"
        decision = _decision(rec).upper()
        op = rec.get("cmd") or rec.get("op") or "-"
        suffix = ""
        if rec.get("bypass"):
            bypass_val = rec["bypass"]
            tag = bypass_val if isinstance(bypass_val, str) else "--yes-i-know"
            suffix = f" (bypass: {tag})"
        lines.append(
            f"{_short(ts_disp, 20)} {_short(pattern, 24)} {decision:<10} {op}{suffix}"
        )
    return "\n".join(lines)


def _render_json(records: list[dict]) -> str:
    out = []
    for rec in records:
        enriched = dict(rec)
        enriched["decision"] = _decision(rec)
        out.append(enriched)
    return json.dumps(out, indent=2, sort_keys=True)


# ── CLI ────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="audit_query.py",
        description="Query Sylph's destructive-op audit log.",
    )
    p.add_argument("--since", metavar="YYYY-MM-DD",
                   help="Include records on or after this UTC date.")
    p.add_argument("--until", metavar="YYYY-MM-DD",
                   help="Include records on or before this UTC date (inclusive).")
    p.add_argument("--pattern", metavar="PATTERN",
                   help="Exact match on the 'pattern' field.")
    p.add_argument("--verdict", choices=("blocked", "allowed", "bypassed"),
                   help="Filter by normalized decision.")
    p.add_argument("--tail", type=int, metavar="N",
                   help="Emit only the last N records after filtering.")
    p.add_argument("--json", action="store_true",
                   help="Emit JSON array (pass-through + 'decision' field).")
    p.add_argument("--audit-log", metavar="PATH",
                   help="Override audit.jsonl path (mostly for tests).")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    audit_path = Path(args.audit_log) if args.audit_log else DEFAULT_AUDIT

    if not audit_path.exists():
        print("no audit entries")
        return 0

    since = _parse_date_bound(args.since, end_of_day=False) if args.since else None
    until = _parse_date_bound(args.until, end_of_day=True) if args.until else None

    if args.tail is not None and args.tail < 0:
        print("audit_query: --tail must be >= 0", file=sys.stderr)
        return 2

    records = list(_iter_records(audit_path))
    records = _apply_filters(
        records,
        since=since,
        until=until,
        pattern=args.pattern,
        verdict=args.verdict,
    )

    if args.tail is not None:
        records = records[-args.tail :] if args.tail > 0 else []

    # Windows default console is cp1252; box-drawing + arrows need UTF-8.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    if args.json:
        print(_render_json(records))
    else:
        print(_render_human(records, since=since, until=until))
    return 0


if __name__ == "__main__":
    sys.exit(main())
