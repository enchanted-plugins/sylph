"""Sylph discard-surface aggregator — listing side of /sylph:discard.

Walks the three hook-driven inboxes and emits a unified view of every
pending record the developer could still drop. This script is **read-only**
— the skill routes the actual discard through ``pending_inbox.py discard``,
which owns the atomic rewrite.

Inboxes surfaced (anchored to ``--root`` or auto-detected repo root):

    plugins/branch-workflow/state/pending-actions.jsonl   → inbox=branch
    plugins/commit-intelligence/state/pending-drafts.jsonl → inbox=commit
    plugins/pr-lifecycle/state/pending-prs.jsonl          → inbox=pr

For each pending record (``executed:false, discarded:false``) we emit an
envelope with stable fields the skill can index into without re-parsing:

    {
      "inbox":       "branch" | "commit" | "pr",
      "path":        "<absolute jsonl path>",
      "index":       <0-based index within that inbox's pending list>,
      "ts":          "<record ts>",
      "summary":     "<one-line human label>",
      "confidence":  <float or null>,
      "executed":    false,
      "record":      { ...full original record... }
    }

CLI — ``/sylph:discard`` shells out:

    python discard_surface.py list [--root <repo>] [--inbox branch|commit|pr]
        Prints a JSON array of envelopes sorted by (inbox, confidence desc,
        ts asc). Filter by ``--inbox`` to narrow to a single surface.

    python discard_surface.py resolve --inbox <name> --index <n> [--root <repo>]
        Prints ``{"path": "...", "ts": "...", "record": {...}}`` for the
        envelope at the given (inbox, index) pair — the skill uses this to
        turn an index-based user input into a ts the CLI can pass to
        ``pending_inbox.py discard``.

Stdlib only. Zero external runtime deps (brand standard).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from pending_inbox import read_pending  # noqa: E402

# (inbox-name, relative-path-under-repo-root, summary-builder-key)
_INBOXES: list[tuple[str, str]] = [
    ("branch", "plugins/branch-workflow/state/pending-actions.jsonl"),
    ("commit", "plugins/commit-intelligence/state/pending-drafts.jsonl"),
    ("pr", "plugins/pr-lifecycle/state/pending-prs.jsonl"),
]


def _default_root() -> Path:
    """Resolve the repo root: two levels above this file (shared/scripts/)."""
    return Path(__file__).resolve().parent.parent.parent


def _summarize(inbox: str, rec: dict[str, Any]) -> str:
    """Produce a single-line label for a pending record.

    Shape differs per inbox — we pick the field most useful to a developer
    scanning the list. Falls back to the ``ts`` when nothing is available.
    """
    if inbox == "branch":
        workflow = rec.get("workflow", "?")
        dom = rec.get("dominant_file", "?")
        conf = rec.get("confidence")
        conf_s = f" conf={conf:.2f}" if isinstance(conf, (int, float)) else ""
        return f"branch suggestion · {workflow} · {dom}{conf_s}"
    if inbox == "commit":
        subj = rec.get("subject") or rec.get("title") or "(no subject)"
        ctype = rec.get("type") or rec.get("suggested_type") or "?"
        return f"commit draft · {ctype} · {subj}"
    if inbox == "pr":
        title = rec.get("title") or rec.get("subject") or "(no title)"
        branch = rec.get("branch") or rec.get("head_ref") or "?"
        return f"pr draft · {branch} · {title}"
    return rec.get("ts", "(unknown ts)")


def _confidence_or_none(rec: dict[str, Any]) -> float | None:
    c = rec.get("confidence")
    if isinstance(c, (int, float)):
        return float(c)
    return None


def _envelopes_for_inbox(
    inbox: str,
    path: Path,
) -> list[dict[str, Any]]:
    """Build the envelope list for one inbox. Missing files yield []."""
    records = read_pending(path)
    pending = [r for r in records if not r.get("executed", False)]
    # Stable order: higher confidence first, then earlier ts first.
    pending.sort(
        key=lambda r: (
            -(_confidence_or_none(r) or 0.0),
            r.get("ts", ""),
        )
    )
    envelopes: list[dict[str, Any]] = []
    for idx, rec in enumerate(pending):
        envelopes.append(
            {
                "inbox": inbox,
                "path": str(path),
                "index": idx,
                "ts": rec.get("ts", ""),
                "summary": _summarize(inbox, rec),
                "confidence": _confidence_or_none(rec),
                "executed": bool(rec.get("executed", False)),
                "record": rec,
            }
        )
    return envelopes


def list_surface(
    root: Path,
    inbox_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Aggregate every pending record across the three inboxes.

    ``inbox_filter`` ∈ {None, "branch", "commit", "pr"} — when set, only
    that inbox is surfaced.
    """
    out: list[dict[str, Any]] = []
    for inbox, rel in _INBOXES:
        if inbox_filter and inbox_filter != inbox:
            continue
        path = root / rel
        out.extend(_envelopes_for_inbox(inbox, path))
    return out


# ── CLI ──────────────────────────────────────────────────────────────────

def _cli_list(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else _default_root()
    inbox = args.inbox
    if inbox and inbox not in {"branch", "commit", "pr"}:
        print(
            json.dumps({"error": f"unknown --inbox: {inbox}"}),
            file=sys.stderr,
        )
        return 2
    envelopes = list_surface(root, inbox_filter=inbox)
    json.dump(envelopes, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


def _cli_resolve(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else _default_root()
    if args.inbox not in {"branch", "commit", "pr"}:
        print(
            json.dumps({"error": f"unknown --inbox: {args.inbox}"}),
            file=sys.stderr,
        )
        return 2
    envelopes = list_surface(root, inbox_filter=args.inbox)
    if args.index < 0 or args.index >= len(envelopes):
        print(
            json.dumps(
                {
                    "error": (
                        f"--index {args.index} out of range; "
                        f"{len(envelopes)} pending in '{args.inbox}'"
                    )
                }
            ),
            file=sys.stderr,
        )
        return 1
    env = envelopes[args.index]
    json.dump(
        {"path": env["path"], "ts": env["ts"], "record": env["record"]},
        sys.stdout,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    sys.stdout.write("\n")
    return 0


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="discard_surface.py",
        description="Aggregate pending records across Sylph's 3 inboxes.",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    p_list = sub.add_parser("list", help="list pending envelopes")
    p_list.add_argument("--root", default=None, help="repo root override")
    p_list.add_argument(
        "--inbox",
        default=None,
        choices=["branch", "commit", "pr"],
        help="filter to a single inbox",
    )

    p_resolve = sub.add_parser(
        "resolve",
        help="resolve (inbox, index) → (path, ts, record)",
    )
    p_resolve.add_argument("--root", default=None, help="repo root override")
    p_resolve.add_argument(
        "--inbox",
        required=True,
        choices=["branch", "commit", "pr"],
    )
    p_resolve.add_argument("--index", required=True, type=int)

    args = parser.parse_args(argv[1:])
    if args.action == "list":
        return _cli_list(args)
    if args.action == "resolve":
        return _cli_resolve(args)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
