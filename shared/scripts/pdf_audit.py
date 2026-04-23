#!/usr/bin/env python3
"""Sylph dark-themed session audit — HTML + best-effort PDF.

Satisfies the brand-standard commitment that every plugin ships a
"dark-themed PDF audit" (CLAUDE.md §Brand standard compliance).

Because Sylph is zero-runtime-dep (stdlib only), we do NOT pull in
reportlab / weasyprint / fpdf / pdfkit. Instead we generate a fully
self-contained dark-themed HTML report (inline CSS, no external assets)
and *attempt* to convert it to PDF by shelling out to whichever headless
renderer happens to be on PATH (wkhtmltopdf, chromium, chrome, msedge).
The HTML alone is the guaranteed artifact — the PDF is best-effort.

Inputs:
    - stats.build_rollup() from shared/scripts/stats.py (Agent 4)
    - plugins/sylph-gate/state/audit.jsonl via audit_query._iter_records
      (optional — graceful fallback if the module or file is absent)

CLI:
    python pdf_audit.py [--period session|day|week|all]
                        [--since YYYY-MM-DD]
                        [--out <prefix>]
                        [--no-convert]
                        [--root <repo-root>]

Exit 0 always on a successful HTML write (whether the PDF conversion
completed or not — the path that did succeed is reported on stdout).
Exit 1 only on hard failures (inputs unreadable, HTML write failed).
Exit 2 on bad CLI args.

Colour palette — GitHub Dark, to match the rest of the sylph docs:
    background  #0D1117
    panel       #161B22
    text        #C9D1D9
    muted       #8B949E
    accent      #58A6FF
    border      #30363D
    success     #3FB950
    warn        #D29922
    danger      #F85149
"""
from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Resolve repo root relative to this file: shared/scripts/pdf_audit.py → ../..
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent

# Make sibling stdlib-ish modules importable when invoked directly.
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import stats  # noqa: E402 — sibling module, same directory.

try:  # audit_query is optional — degrade gracefully if it moves or is absent.
    import audit_query  # type: ignore  # noqa: E402
except Exception:  # pragma: no cover — defensive, stdlib should never fail here.
    audit_query = None  # type: ignore[assignment]


# ── Root / period resolution (mirrors stats.py) ────────────────────────

def _resolve_root(explicit: str | None) -> Path:
    import os

    if explicit:
        return Path(explicit).resolve()
    env = os.environ.get("SYLPH_REPO_ROOT")
    if env:
        return Path(env).resolve()
    return REPO_ROOT


# ── Gate / audit fetch ─────────────────────────────────────────────────

def _load_gate_records(root: Path, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Pull sylph-gate audit records in the window. Graceful on every failure.

    Priority order:
        1. audit_query._iter_records when the module is importable and the
           log exists — this gives us the richer field set.
        2. Fallback — raw JSONL parse via stats._read_jsonl.
        3. Empty list on any error.
    """
    audit_path = root / "plugins" / "sylph-gate" / "state" / "audit.jsonl"
    if not audit_path.is_file():
        return []

    records: list[dict[str, Any]] = []
    if audit_query is not None:
        try:
            records = list(audit_query._iter_records(audit_path))
        except Exception:
            records = []
    if not records:
        records = stats._read_jsonl(audit_path)  # type: ignore[attr-defined]

    # Filter into window — reuse stats._in_window so date semantics match.
    return [r for r in records if stats._in_window(r, start, end)]  # type: ignore[attr-defined]


def _classify_gate(rec: dict[str, Any]) -> str:
    """Prefer audit_query's normalised decision; fall back to the raw field."""
    if audit_query is not None:
        try:
            return str(audit_query._decision(rec))
        except Exception:
            pass
    dec = rec.get("decision") or rec.get("outcome") or rec.get("action") or "other"
    return str(dec)


# ── HTML rendering ─────────────────────────────────────────────────────

_CSS = """
:root {
  --bg: #0D1117;
  --panel: #161B22;
  --text: #C9D1D9;
  --muted: #8B949E;
  --accent: #58A6FF;
  --border: #30363D;
  --success: #3FB950;
  --warn: #D29922;
  --danger: #F85149;
}
* { box-sizing: border-box; }
html, body {
  margin: 0;
  padding: 0;
  background: #0D1117;
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue",
               Arial, "Noto Sans", sans-serif;
  font-size: 14px;
  line-height: 1.55;
}
body { padding: 2rem 2.5rem; max-width: 960px; margin: 0 auto; }
header { border-bottom: 1px solid var(--border); padding-bottom: 1rem; margin-bottom: 1.5rem; }
header h1 { margin: 0 0 .25rem; font-size: 1.7rem; color: var(--accent); }
header .period { margin: 0; color: var(--muted); font-size: .9rem; }
section {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 1rem 1.25rem;
  margin-bottom: 1.25rem;
}
section h2 {
  margin: 0 0 .75rem;
  font-size: 1.1rem;
  color: var(--accent);
  border-bottom: 1px solid var(--border);
  padding-bottom: .4rem;
}
table { width: 100%; border-collapse: collapse; }
th, td {
  text-align: left;
  padding: .4rem .6rem;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
}
th { color: var(--muted); font-weight: 600; font-size: .85rem; text-transform: uppercase; letter-spacing: .04em; }
tr:last-child td { border-bottom: none; }
code, pre, .mono { font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace; font-size: .85rem; }
.badge {
  display: inline-block;
  padding: .1rem .5rem;
  border-radius: 999px;
  font-size: .75rem;
  border: 1px solid var(--border);
  background: #0D1117;
  color: var(--muted);
}
.badge.ok { color: var(--success); border-color: var(--success); }
.badge.warn { color: var(--warn); border-color: var(--warn); }
.badge.danger { color: var(--danger); border-color: var(--danger); }
.kv { display: grid; grid-template-columns: 18rem 1fr; gap: .25rem 1rem; }
.kv dt { color: var(--muted); }
.kv dd { margin: 0; }
.muted { color: var(--muted); }
.empty { color: var(--muted); font-style: italic; }
footer { margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--border); color: var(--muted); font-size: .8rem; text-align: center; }

/* Print: keep the dark theme when rendered to PDF. */
@media print {
  @page { size: A4; margin: 15mm; background: #0D1117; }
  html, body { background: #0D1117 !important; color: var(--text) !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  body { padding: 0; max-width: none; }
  section { page-break-inside: avoid; background: #161B22 !important; border: 1px solid #30363D !important; }
  header h1, section h2 { color: #58A6FF !important; }
  a { color: var(--accent); }
}
"""


def _esc(value: Any) -> str:
    if value is None:
        return "—"
    return html.escape(str(value), quote=False)


def _fmt_float(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return _esc(value)


def _fmt_dt(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return _esc(iso)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _counts_table(counter: dict[str, int], key_label: str, value_label: str = "count") -> str:
    if not counter:
        return '<p class="empty">No data in this window.</p>'
    rows: list[str] = [
        f"<tr><th>{_esc(key_label)}</th><th>{_esc(value_label)}</th></tr>"
    ]
    for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])):
        rows.append(f"<tr><td class=\"mono\">{_esc(k)}</td><td>{_esc(v)}</td></tr>")
    return "<table>" + "".join(rows) + "</table>"


def _section_summary(rollup: dict[str, Any]) -> str:
    window = rollup.get("window", {})
    kv = [
        ("Window start", _fmt_dt(window.get("start", ""))),
        ("Window end", _fmt_dt(window.get("end", ""))),
        ("Boundaries detected", rollup.get("boundaries_detected", 0)),
        ("Boundaries uncertain (→ Opus)", rollup.get("boundaries_uncertain", 0)),
        ("Avg W2 distance", _fmt_float(rollup.get("boundary_avg_distance"))),
        ("Branches suggested", rollup.get("branches_suggested", 0)),
        ("Avg W3 confidence", _fmt_float(rollup.get("branch_avg_confidence"))),
        ("Commits drafted", rollup.get("commits_drafted", 0)),
        ("PRs drafted", rollup.get("prs_drafted", 0)),
        ("Gate decisions total", rollup.get("gate_decisions_total", 0)),
        ("Pending actions / drafts / PRs",
         f"{rollup.get('pending_actions', 0)} / "
         f"{rollup.get('pending_drafts', 0)} / "
         f"{rollup.get('pending_prs', 0)}"),
    ]
    rows = "".join(
        f"<dt>{_esc(k)}</dt><dd>{_esc(v)}</dd>" for k, v in kv
    )
    return (
        '<section id="summary"><h2>Summary</h2>'
        f'<dl class="kv">{rows}</dl></section>'
    )


def _section_boundaries(rollup: dict[str, Any]) -> str:
    n = rollup.get("boundaries_detected", 0)
    unc = rollup.get("boundaries_uncertain", 0)
    avg = _fmt_float(rollup.get("boundary_avg_distance"))
    body = (
        f"<p>{_esc(n)} boundaries detected — {_esc(unc)} flagged uncertain "
        f"(confidence &lt; 0.7, routed to the Opus boundary-detector agent). "
        f"Average W2 distance: <span class=\"mono\">{_esc(avg)}</span>.</p>"
    )
    if not n:
        body += '<p class="empty">Nothing fired in this window.</p>'
    return f'<section id="boundaries"><h2>Boundaries detected</h2>{body}</section>'


def _section_branches(rollup: dict[str, Any]) -> str:
    wf = rollup.get("branch_workflows") or {}
    n = rollup.get("branches_suggested", 0)
    avg = _fmt_float(rollup.get("branch_avg_confidence"))
    summary = (
        f'<p>{_esc(n)} branch suggestions across {_esc(len(wf))} workflow patterns '
        f'(avg W3 confidence <span class="mono">{_esc(avg)}</span>).</p>'
    )
    return (
        '<section id="branches"><h2>Branches suggested</h2>'
        f'{summary}{_counts_table(wf, "workflow")}</section>'
    )


def _section_commits(rollup: dict[str, Any]) -> str:
    ct = rollup.get("commit_types") or {}
    n = rollup.get("commits_drafted", 0)
    summary = f"<p>{_esc(n)} commits drafted by W1 (Myers-Diff Conventional Classifier).</p>"
    return (
        '<section id="commits"><h2>Commits drafted</h2>'
        f'{summary}{_counts_table(ct, "type")}</section>'
    )


def _section_prs(rollup: dict[str, Any]) -> str:
    n = rollup.get("prs_drafted", 0)
    body = (
        f"<p>{_esc(n)} draft PRs opened by W4 in this window.</p>"
        '<p class="muted">pr-lifecycle emits via the enchanted-mcp event bus.</p>'
    )
    return f'<section id="prs"><h2>PRs drafted</h2>{body}</section>'


def _section_gate(rollup: dict[str, Any], gate_records: list[dict[str, Any]]) -> str:
    decisions = rollup.get("gate_decisions") or {}
    blocked = rollup.get("gate_blocked_categories") or {}

    rows: list[str] = [
        '<tr><th>ts (UTC)</th><th>pattern</th><th>decision</th><th>op</th></tr>'
    ]
    for rec in gate_records[-25:]:  # last 25 in-window
        ts_raw = rec.get("ts", "")
        pattern = rec.get("pattern") or rec.get("category") or "—"
        decision = _classify_gate(rec)
        op = rec.get("cmd") or rec.get("op") or "—"
        cls = "badge"
        if decision in ("blocked", "block", "deny", "denied"):
            cls += " danger"
        elif decision in ("bypassed",):
            cls += " warn"
        elif decision in ("allowed",):
            cls += " ok"
        rows.append(
            f'<tr><td class="mono">{_esc(ts_raw)}</td>'
            f'<td class="mono">{_esc(pattern)}</td>'
            f'<td><span class="{cls}">{_esc(decision)}</span></td>'
            f'<td class="mono">{_esc(op)}</td></tr>'
        )

    trailing = "<table>" + "".join(rows) + "</table>" if gate_records else \
        '<p class="empty">No destructive-op decisions recorded in this window.</p>'

    return (
        '<section id="gate"><h2>Gate decisions</h2>'
        f'<h3 class="muted" style="font-size:.95rem">Decision mix</h3>{_counts_table(dict(decisions), "decision")}'
        f'<h3 class="muted" style="font-size:.95rem">Blocked categories</h3>{_counts_table(dict(blocked), "category")}'
        f'<h3 class="muted" style="font-size:.95rem">Recent entries</h3>{trailing}'
        '</section>'
    )


def _section_churn(rollup: dict[str, Any]) -> str:
    churn = rollup.get("top_file_churn") or []
    if not churn:
        body = '<p class="empty">No edit events observed in this window.</p>'
    else:
        rows = ['<tr><th>path</th><th>events</th></tr>']
        for path, count in churn:
            rows.append(
                f'<tr><td class="mono">{_esc(path)}</td><td>{_esc(count)}</td></tr>'
            )
        body = "<table>" + "".join(rows) + "</table>"
    return f'<section id="churn"><h2>Top files by churn</h2>{body}</section>'


def _section_session(rollup: dict[str, Any], root: Path) -> str:
    learning = rollup.get("learning") or {}
    kv: list[tuple[str, Any]] = [
        ("Repo root", str(root)),
        ("Learning samples", learning.get("sample_count", 0)),
        ("Learning confident", "yes" if learning.get("confident") else "no"),
        ("Learning schema", learning.get("schema_version") or "—"),
    ]
    rows = "".join(
        f"<dt>{_esc(k)}</dt><dd>{_esc(v)}</dd>" for k, v in kv
    )
    return (
        '<section id="session"><h2>Session context</h2>'
        f'<dl class="kv">{rows}</dl>'
        '<p class="muted">Generated stdlib-only — no reportlab, no weasyprint. '
        'Open this file in a browser and Print → Save as PDF for a PDF copy '
        'when the automatic conversion path did not complete.</p>'
        '</section>'
    )


def render_html(rollup: dict[str, Any], gate_records: list[dict[str, Any]],
                root: Path, period_label: str, now: datetime) -> str:
    title = f"Sylph Session Audit — {now.strftime('%Y-%m-%d')}"
    window = rollup.get("window", {})
    period = (
        f"{period_label} · "
        f"{_fmt_dt(window.get('start', ''))} → {_fmt_dt(window.get('end', ''))}"
    )
    parts = [
        "<!doctype html>",
        '<html lang="en"><head>',
        '<meta charset="utf-8">',
        f"<title>{_esc(title)}</title>",
        f"<style>{_CSS}</style>",
        "</head><body>",
        '<header>',
        f'<h1>{_esc(title)}</h1>',
        f'<p class="period">{_esc(period)}</p>',
        '</header>',
        _section_summary(rollup),
        _section_boundaries(rollup),
        _section_branches(rollup),
        _section_commits(rollup),
        _section_prs(rollup),
        _section_gate(rollup, gate_records),
        _section_churn(rollup),
        _section_session(rollup, root),
        f'<footer>Generated by Sylph W5 — {_esc(now.strftime("%Y-%m-%dT%H:%M:%SZ"))}</footer>',
        "</body></html>",
    ]
    return "\n".join(parts)


# ── PDF conversion (best-effort) ───────────────────────────────────────

def _candidate_converters(html_path: Path, pdf_path: Path) -> list[list[str]]:
    """Platform-aware converter commands, in preference order."""
    hp = str(html_path)
    pp = str(pdf_path)
    candidates: list[list[str]] = [
        ["wkhtmltopdf", "--enable-local-file-access", hp, pp],
        ["chromium", "--headless", "--disable-gpu", "--no-sandbox",
         f"--print-to-pdf={pp}", hp],
        ["chromium-browser", "--headless", "--disable-gpu", "--no-sandbox",
         f"--print-to-pdf={pp}", hp],
        ["google-chrome", "--headless", "--disable-gpu", "--no-sandbox",
         f"--print-to-pdf={pp}", hp],
        ["chrome", "--headless", "--disable-gpu", "--no-sandbox",
         f"--print-to-pdf={pp}", hp],
    ]
    if sys.platform == "win32":
        candidates.insert(0, [
            "msedge.exe", "--headless", "--disable-gpu",
            f"--print-to-pdf={pp}", hp,
        ])
        candidates.insert(1, [
            "msedge", "--headless", "--disable-gpu",
            f"--print-to-pdf={pp}", hp,
        ])
    return candidates


def try_convert(html_path: Path, pdf_path: Path) -> tuple[bool, str]:
    """Attempt headless conversion. Return (ok, tool_used_or_reason)."""
    for cmd in _candidate_converters(html_path, pdf_path):
        if not shutil.which(cmd[0]):
            continue
        try:
            subprocess.run(
                cmd,
                check=True,
                timeout=30,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            continue
        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            return True, cmd[0]
    return False, "no headless renderer on PATH"


# ── CLI ─────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sylph-pdf-audit",
        description=(
            "Render a dark-themed HTML session audit (stdlib only). "
            "Also attempts best-effort PDF conversion via wkhtmltopdf / "
            "chromium / chrome / msedge when available. If none of those "
            "are on PATH, open the generated .html in a browser and "
            "Print → Save as PDF."
        ),
    )
    p.add_argument(
        "--period",
        choices=("session", "day", "week", "all"),
        default="session",
        help="time window (default: session)",
    )
    p.add_argument(
        "--since",
        help="explicit start date YYYY-MM-DD (overrides --period)",
    )
    p.add_argument(
        "--out",
        help="output path prefix (writes <prefix>.html and <prefix>.pdf). "
             "Default: ./sylph-audit-<YYYY-MM-DD>",
    )
    p.add_argument(
        "--no-convert",
        action="store_true",
        help="skip PDF conversion; write HTML only",
    )
    p.add_argument(
        "--root",
        help="override repo root (testing). Falls back to SYLPH_REPO_ROOT env.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    root = _resolve_root(args.root)

    try:
        start, end = stats._resolve_window(args.period, args.since, root)  # type: ignore[attr-defined]
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover — defensive.
        print(f"pdf_audit: failed to resolve window: {exc}", file=sys.stderr)
        return 1

    try:
        rollup = stats.build_rollup(root, start, end)
    except Exception as exc:
        print(f"pdf_audit: stats.build_rollup failed: {exc}", file=sys.stderr)
        return 1

    try:
        gate_records = _load_gate_records(root, start, end)
    except Exception:
        gate_records = []  # never let a dirty audit log abort the report.

    now = datetime.now(tz=timezone.utc)

    if args.out:
        prefix = Path(args.out).expanduser().resolve()
    else:
        prefix = Path.cwd().resolve() / f"sylph-audit-{now.strftime('%Y-%m-%d')}"

    html_path = prefix.with_suffix(".html")
    pdf_path = prefix.with_suffix(".pdf")

    period_label = "since" if args.since else args.period
    doc = render_html(rollup, gate_records, root, period_label, now)

    try:
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(doc, encoding="utf-8")
    except OSError as exc:
        print(f"pdf_audit: failed to write {html_path}: {exc}", file=sys.stderr)
        return 1

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    print(f"HTML report: {html_path}")

    if args.no_convert:
        print("PDF conversion: skipped (--no-convert)")
        return 0

    ok, info = try_convert(html_path, pdf_path)
    if ok:
        print(f"PDF report:  {pdf_path}  (via {info})")
    else:
        print(
            f"PDF conversion: unavailable ({info}). "
            f"Open {html_path} in a browser and use Print \u2192 Save as PDF."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
