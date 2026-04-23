---
name: sylph:stats
description: Observability rollup across every Sylph plugin — boundaries detected, branches suggested, commits drafted, gate decisions, pending inboxes, and top files by edit churn. Reads every plugin's state/metrics.jsonl and the sylph-gate audit log; never mutates anything.
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/stats.py *), Bash(python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/stats.py *), Read(plugins/*/state/metrics.jsonl), Read(plugins/sylph-gate/state/audit.jsonl), Read(plugins/sylph-learning/state/learnings.json)
---

# /sylph:stats

Surface the raw event stream every Sylph hook writes into one glance.

## Usage

```
/sylph:stats                         # current session (last SessionStart → now)
/sylph:stats --period day            # today UTC
/sylph:stats --period week           # last 7 days
/sylph:stats --period all            # everything on disk
/sylph:stats --since 2026-04-15      # explicit start date
/sylph:stats --json                  # structured output for piping
```

## What it shows

```
Sylph — session stats (2026-04-21 14:00 → 16:23)
─────────────────────────────────────────────────
Boundaries detected:       7   (W2 avg distance: 0.42, 2 routed to Opus judgment)
Branches suggested:        5   (3 workflows: github-flow × 4, trunk × 1)
Commits drafted:           5   (feat × 3, fix × 1, docs × 1)
PRs drafted:               0
Gate decisions:            2 blocked (force-push × 1, amend-of-pushed × 1)
Pending inbox:                5 actions, 5 drafts, 0 PRs

Top files by edit churn: src/auth.py (12), docs/README.md (3)
```

## Where it reads from

- `plugins/boundary-segmenter/state/metrics.jsonl` — W2 boundary events
- `plugins/branch-workflow/state/metrics.jsonl` — W3 workflow observations
- `plugins/commit-intelligence/state/metrics.jsonl` — W1 type suggestions
- `plugins/sylph-gate/state/audit.jsonl` — destructive-op decisions
- `plugins/*/state/pending-*.jsonl` — outstanding inbox counts
- `plugins/sylph-learning/state/learnings.json` — W5 sample count

Missing files count as 0. The tool never errors on a fresh install.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Rollup printed |
| 2 | Bad CLI args (invalid `--period`, malformed `--since`) |
