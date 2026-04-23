---
name: sylph:audit
description: Query the sylph-gate destructive-op audit log — "did Sylph block anything this week?" answered in one line. Filters by date window, pattern, verdict.
---

# /sylph:audit

Every destructive git op sylph-gate evaluates lands in
`plugins/sylph-gate/state/audit.jsonl` — one record per decision. This
command is the read-only query surface over that log.

## Usage

```
/sylph:audit                               # full log, human table
/sylph:audit --since 2026-04-14            # last week
/sylph:audit --verdict blocked             # what did Sylph actually stop?
/sylph:audit --pattern force_push_protected
/sylph:audit --since 2026-04-01 --until 2026-04-15 --json
/sylph:audit --tail 20                     # most-recent 20 after filtering
```

## Filters

| Flag | Semantics |
|------|-----------|
| `--since YYYY-MM-DD` | inclusive lower bound on the `ts` field (UTC) |
| `--until YYYY-MM-DD` | inclusive upper bound (end-of-day UTC) |
| `--pattern NAME` | exact match on the classifier's `pattern` id |
| `--verdict blocked\|allowed\|bypassed` | normalized decision (bypassed beats verdict_exit) |
| `--tail N` | keep only the last N records after filtering |
| `--json` | machine-readable output (pass-through + `decision` field) |

## What you'll see

Human mode prints a single-line header plus one row per decision:
`ts`, `pattern`, `verdict`, the command, and (if applicable) the bypass tag.
JSON mode emits the full record array including every source field the
producer wrote plus a normalized `decision` in `{blocked, allowed, bypassed}`.

## What it will *not* do

- It will not mutate `audit.jsonl`. Ever. Consumer-only.
- It will not infer records from `git reflog` or any other source —
  the gate is the sole producer.
- No matches is not an error. Exit code 0 with "no audit entries match."
