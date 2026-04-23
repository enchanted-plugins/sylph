"""Sylph pending-inbox helper — the consumer side of the hook-driven inbox.

Two Sylph hook scripts append advisory records to JSONL inboxes:

    plugins/branch-workflow/state/pending-actions.jsonl
    plugins/commit-intelligence/state/pending-drafts.jsonl

The ``/sylph:branch`` and ``/sylph:commit`` skill commands are the consumers.
This module gives them two small primitives:

    read_pending(path) -> list[dict]
        Read every JSONL record. Corrupt lines are skipped silently (hook
        appends are best-effort; a torn last line should not poison a whole
        session).

    mark_executed(path, record_ts, **fields) -> bool
        Atomically rewrite the file so the record whose ``ts`` matches
        ``record_ts`` is flipped to ``executed:true`` with any extra fields
        merged in (e.g. ``branch_name=<name>`` or ``sha=<sha>``). Returns
        True iff a matching record was found and rewritten. Ordering is
        preserved. Re-uses ``atomic_state.write_state``'s same-directory
        tempfile + ``os.replace`` pattern, adapted for JSONL output.

    mark_discarded(path, record_ts, reason=None) -> bool
        Mirror of ``mark_executed`` for the rollback surface. Flips the
        matching record to ``executed:false, discarded:true`` with a
        ``discarded_at`` UTC ISO-8601 stamp and optional ``discard_reason``
        note. Re-discarding a record that is already ``discarded:true`` is
        a no-op (returns True without rewriting). ``read_pending`` excludes
        discarded records — they're terminal provenance, not pending.

CLI — the skill commands shell out rather than importing:

    python pending_inbox.py read  <path>
        Prints a JSON array of pending (executed=false, discarded=false)
        records to stdout. The array is sorted by descending ``confidence``
        (where present), then by ``ts`` ascending, so the highest-confidence
        suggestion is always element 0 — the default shown to the developer.

    python pending_inbox.py mark  <path> <record_ts> [k=v ...]
        Marks the record matching <record_ts> as executed and merges any
        ``key=value`` pairs from argv into the rewritten record. Exits 0
        on success, 1 if no matching record was found.

    python pending_inbox.py discard <path> <record_ts> [reason="..."]
        Marks the record matching <record_ts> as discarded. Exits 0 on
        success (including the already-discarded no-op), 1 if no record
        with that ts exists at all.

Stdlib only. Zero external runtime deps (brand standard).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Union

# Re-use the canonical atomic primitives — keep one source of truth for the
# Emu-A4 pattern.
_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from atomic_state import read_state  # noqa: E402,F401  (re-export friendly)

PathLike = Union[str, "os.PathLike[str]", Path]


def read_pending(path: PathLike) -> list[dict[str, Any]]:
    """Read every JSONL record from ``path``, excluding discarded ones.

    Returns ``[]`` when the file is missing or empty. Corrupt lines (a
    half-written tail, a hook race) are skipped silently — the consumer
    should never crash on inbox rot.

    Records carrying ``discarded:true`` are filtered out here — they are
    terminal provenance (W5 still reads them as a negative EMA signal),
    but callers asking for "pending" never want to see them again.
    """
    p = Path(path)
    if not p.exists():
        return []
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return []
    if not raw.strip():
        return []

    records: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            if rec.get("discarded", False):
                continue
            records.append(rec)
    return records


def _atomic_write_lines(path: Path, lines: list[str]) -> None:
    """Atomically rewrite ``path`` from a list of already-encoded JSONL lines.

    Same pattern as ``atomic_state.write_state`` — tempfile in the same
    directory, fsync, ``os.replace``. Each line is emitted as-is with a
    trailing newline; ordering is preserved by the caller.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(line)
                if not line.endswith("\n"):
                    f.write("\n")
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # Rare: unsupported on some Windows network mounts. The
                # os.replace below still gives the atomic-swap guarantee.
                pass
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def mark_executed(path: PathLike, record_ts: str, **fields: Any) -> bool:
    """Flip the record with matching ``ts`` to ``executed:true``.

    Any keyword args are merged into the record — commonly ``branch_name``
    for /sylph:branch or ``sha`` for /sylph:commit. An ``executed_at``
    UTC ISO-8601 timestamp is always set.

    Returns True iff a matching record was found. When False, the file is
    left untouched (no I/O). When True, the file is atomically rewritten
    preserving original line order.
    """
    p = Path(path)
    if not p.exists():
        return False
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return False
    if not raw.strip():
        return False

    # Parse → mutate-if-match → re-serialize. We preserve corrupt lines
    # as-is (passed through); they were already there before and rewriting
    # shouldn't drop them silently.
    from datetime import datetime, timezone

    executed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    new_lines: list[str] = []
    matched = False
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            # Drop empty lines — they're noise, not data.
            continue
        try:
            rec = json.loads(stripped)
        except json.JSONDecodeError:
            # Preserve corrupt-but-present line. A later append will still
            # find a clean tail because it uses O_APPEND.
            new_lines.append(stripped)
            continue
        if (
            not matched
            and isinstance(rec, dict)
            and rec.get("ts") == record_ts
            and not rec.get("executed", False)
        ):
            rec["executed"] = True
            rec["executed_at"] = executed_at
            for k, v in fields.items():
                rec[k] = v
            matched = True
        new_lines.append(
            json.dumps(rec, separators=(",", ":"), ensure_ascii=False)
        )

    if not matched:
        return False

    _atomic_write_lines(p, new_lines)
    return True


def mark_discarded(
    path: PathLike,
    record_ts: str,
    reason: str | None = None,
) -> bool:
    """Flip the record with matching ``ts`` to ``discarded:true``.

    The discarded record is rewritten with:

        executed:       false      (a discard is never also an execution)
        discarded:      true
        discarded_at:   <UTC ISO-8601>
        discard_reason: <reason>   (omitted when None)

    Re-discarding an already-discarded record is a no-op: the function
    returns True (the record "is discarded") without rewriting the file.
    This makes the CLI idempotent — rerunning discard with the same ts is
    safe and doesn't trip the no-match exit.

    Returns True iff a record with matching ``ts`` exists. When no such
    record is present, returns False and the file is left untouched.

    Note: ``executed:true, sha:<sha>`` / ``branch_name:<name>`` /
    ``pr_number:<n>`` records can still be discarded — the side-effect
    is not undone by this function, but provenance is flipped so the
    record no longer shows up in ``read_pending`` and W5 can treat the
    original suggestion as a negative signal.

    # TODO: emit discard signal to sylph-learning for W5 EMA
    """
    p = Path(path)
    if not p.exists():
        return False
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return False
    if not raw.strip():
        return False

    from datetime import datetime, timezone

    discarded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    new_lines: list[str] = []
    matched = False
    rewrote = False
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            rec = json.loads(stripped)
        except json.JSONDecodeError:
            # Preserve corrupt-but-present line; same contract as mark_executed.
            new_lines.append(stripped)
            continue
        if (
            not matched
            and isinstance(rec, dict)
            and rec.get("ts") == record_ts
        ):
            matched = True
            if rec.get("discarded", False):
                # Idempotent no-op: already discarded, don't rewrite the file.
                new_lines.append(
                    json.dumps(rec, separators=(",", ":"), ensure_ascii=False)
                )
                continue
            rec["executed"] = False
            rec["discarded"] = True
            rec["discarded_at"] = discarded_at
            if reason:
                rec["discard_reason"] = reason
            rewrote = True
        new_lines.append(
            json.dumps(rec, separators=(",", ":"), ensure_ascii=False)
        )

    if not matched:
        return False

    if rewrote:
        _atomic_write_lines(p, new_lines)
    return True


# ── CLI ──────────────────────────────────────────────────────────────────

def _confidence_key(rec: dict[str, Any]) -> float:
    """Sort key: higher confidence first, then older ts first (FIFO tiebreak)."""
    try:
        c = float(rec.get("confidence", 0) or 0)
    except (TypeError, ValueError):
        c = 0.0
    return -c


def _cli_read(path: str) -> int:
    records = read_pending(path)
    # read_pending already filters discarded records; strip executed here too.
    pending = [r for r in records if not r.get("executed", False)]
    # Highest confidence first; stable on ties (Python sort is stable) keeps
    # the earlier ts first.
    pending.sort(key=_confidence_key)
    json.dump(pending, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


def _cli_mark(path: str, ts: str, extras: list[str]) -> int:
    fields: dict[str, Any] = {}
    for pair in extras:
        if "=" not in pair:
            print(
                json.dumps({"error": f"expected key=value, got: {pair}"}),
                file=sys.stderr,
            )
            return 2
        k, v = pair.split("=", 1)
        fields[k] = v
    ok = mark_executed(path, ts, **fields)
    if not ok:
        print(
            json.dumps({"error": f"no pending record with ts={ts}"}),
            file=sys.stderr,
        )
        return 1
    return 0


def _cli_discard(path: str, ts: str, extras: list[str]) -> int:
    """CLI: ``pending_inbox.py discard <path> <ts> [reason="..."]``.

    Accepts a single optional ``reason="human note"`` or bare ``reason=note``.
    Unknown keys are rejected with exit 2. Unknown ts exits 1.
    """
    reason: str | None = None
    for pair in extras:
        if "=" not in pair:
            print(
                json.dumps({"error": f"expected key=value, got: {pair}"}),
                file=sys.stderr,
            )
            return 2
        k, v = pair.split("=", 1)
        if k != "reason":
            print(
                json.dumps({"error": f"unknown key for discard: {k}"}),
                file=sys.stderr,
            )
            return 2
        # Strip surrounding quotes the shell might have left when the caller
        # quoted the value but the arg arrived as a single token.
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
            v = v[1:-1]
        reason = v
    ok = mark_discarded(path, ts, reason=reason)
    if not ok:
        print(
            json.dumps({"error": f"no record with ts={ts}"}),
            file=sys.stderr,
        )
        return 1
    return 0


def _main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(
            "usage: pending_inbox.py (read|mark|discard) <path> [args...]",
            file=sys.stderr,
        )
        return 2
    action, path = argv[1], argv[2]
    if action == "read":
        return _cli_read(path)
    if action == "mark":
        if len(argv) < 4:
            print(
                "usage: pending_inbox.py mark <path> <record_ts> [k=v ...]",
                file=sys.stderr,
            )
            return 2
        return _cli_mark(path, argv[3], argv[4:])
    if action == "discard":
        if len(argv) < 4:
            print(
                'usage: pending_inbox.py discard <path> <record_ts> [reason="..."]',
                file=sys.stderr,
            )
            return 2
        return _cli_discard(path, argv[3], argv[4:])
    print(f"unknown action: {action}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
