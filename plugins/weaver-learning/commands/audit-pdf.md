---
name: sylph:audit-pdf
description: Dark-themed Sylph session audit — renders a self-contained HTML report (GitHub dark palette, @media print tuned) from the same rollup /sylph:stats consumes, then attempts best-effort PDF conversion via wkhtmltopdf / chromium / chrome / msedge if any of them are on PATH. Primary artifact is always the HTML; if the automatic PDF path did not complete, open the HTML in a browser and Print → Save as PDF.
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/pdf_audit.py *), Bash(python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/pdf_audit.py *), Read(plugins/*/state/metrics.jsonl), Read(plugins/sylph-gate/state/audit.jsonl), Read(plugins/sylph-learning/state/learnings.json)
---

# /sylph:audit-pdf

Ship the brand-standard dark-themed PDF audit (CLAUDE.md §Brand standard
compliance — "Dark-themed PDF audit. Ships from each plugin on final
release.").

## Usage

```
/sylph:audit-pdf                         # current session → ./sylph-audit-<YYYY-MM-DD>.html(.pdf)
/sylph:audit-pdf --period day            # today UTC
/sylph:audit-pdf --period week           # last 7 days
/sylph:audit-pdf --period all            # everything on disk
/sylph:audit-pdf --since 2026-04-15      # explicit start date
/sylph:audit-pdf --out ./audits/session  # custom prefix (writes .html and .pdf)
/sylph:audit-pdf --no-convert            # HTML only, skip PDF attempt
```

## What it produces

- **`<prefix>.html`** — always. A single self-contained file, inline CSS,
  GitHub-dark palette (`#0D1117` background, `#C9D1D9` text, `#58A6FF`
  accent, `#30363D` borders), tuned for `@media print` so Print → Save as
  PDF in any browser produces a clean dark-themed PDF.
- **`<prefix>.pdf`** — best-effort. The script probes PATH for
  `wkhtmltopdf`, `chromium`, `chromium-browser`, `google-chrome`,
  `chrome`, and (on Windows) `msedge` / `msedge.exe`. Whichever one is
  found first wins; if none is found, the PDF is skipped and the HTML
  fallback is surfaced.

## Sections

- **Summary** — window, boundaries, branches, commits, PRs, gate, pending inbox
- **Boundaries detected** — W2 count, uncertain routing, avg distance
- **Branches suggested** — W3 workflow mix
- **Commits drafted** — W1 type distribution
- **PRs drafted** — W4 counter (event bus)
- **Gate decisions** — decision mix, blocked categories, last 25 audit rows
- **Top files by churn** — 5 busiest paths from W2 observation stream
- **Session context** — repo root, W5 sample count + confidence

## Zero external deps

Stdlib only — no `reportlab`, `weasyprint`, `fpdf`, `pdfkit`. The HTML is
the primary artifact; the PDF is a convenience. If you need a PDF on a
machine without any headless browser, open the HTML and Print → Save as
PDF. The `@media print` CSS keeps the dark theme in the exported PDF.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | HTML written (PDF may or may not have converted — stdout reports which) |
| 1 | Hard failure: rollup unreadable, HTML write failed |
| 2 | Bad CLI args (invalid `--period`, malformed `--since`) |
