---
name: sylph:learnings
description: Show W5 Gauss Learning priors — what Sylph has learned about the developer's commit style, branch naming, reviewer overrides, and W2 boundary corrections. Surfaces the signals that drive per-developer adaptation.
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/gauss_learning.py *), Bash(python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/gauss_learning.py *), Read(plugins/sylph-learning/state/learnings.json), Read(plugins/sylph-learning/state/priors.json)
---

# /sylph:learnings

Show what W5 has absorbed about your workflow patterns.

## Usage

```
/sylph:learnings                    # print the priors summary
/sylph:learnings --full             # print the raw learnings.json
/sylph:learnings --reset            # wipe state (requires confirmation; destructive)
/sylph:learnings --export path.json # copy priors to a shareable file
```

## What it shows

```
Sylph Learning — 47 samples observed, confident=True

Commit style:
  Scope usage rate:         0.72   (most commits include a (scope))
  Body present rate:        0.41
  Avg subject length:       52 chars
  Top types:                feat (0.38) fix (0.29) docs (0.15) chore (0.10) refactor (0.08)
  Top scopes:               auth (0.31) api (0.24) db (0.12) ui (0.09) docs (0.08)

Branch naming:
  Slug style:               kebab-case
  Type prefix rate:         0.89   (feat/x, fix/y — matches github-flow)
  User prefix rate:         0.04
  Bootstrap:                cleared at sample 10

PR turnaround (last 30 days):
  Median hours to first review:  4.2
  Median hours to merge:         18.7

W2 corrections:
  boundary_overrides:       3
  false_split:              2  (cluster fired when developer wanted them merged)
  false_merge:              1  (cluster held when developer wanted them split)

Reviewer overrides:
  @tech-lead:               +0.82    (added manually 5 times; W4 will prefer)
  @junior:                  -0.34    (removed manually; W4 will de-prioritize)
```

## How priors flow back

| Signal | Consumed by | Effect |
|---|---|---|
| `top_scopes` | W1 (commit-drafter) | Biases scope selection when the diff is ambiguous |
| `slug_style` | W3 (branch naming) | Kebab vs snake vs mixed |
| `type_prefix_rate` | W3 | Forces `type/slug` when > 0.7 |
| `false_split` / `false_merge` | W2 | Tunes α/β/γ weights for future sessions |
| `reviewer_overrides` | W4 | Up-/down-weights candidates |
| `pr_turnaround` | W4 | Weighs availability signal |

## --reset semantics

Wipes `plugins/sylph-learning/state/learnings.json`. Routed through
sylph-gate as a destructive-op (reflog doesn't cover this). Useful when:

- You're shipping Sylph to a team machine and want fresh priors.
- The learning has drifted badly (rare but possible — bootstrap floor
  doesn't prevent poisoned samples).

The `.priors.json` session cache is regenerated on next SessionStart
from whatever `learnings.json` exists.

## Confidence flag

Under the bootstrap floor (`SYLPH_GAUSS_BOOTSTRAP_MIN_SAMPLES`, default
10), priors are returned with `confident=False` and downstream engines
ignore them — using `shared/constants.sh` defaults instead. The bar
prevents sample-of-1 signals from dictating W1/W2/W3/W4 behavior.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Priors printed |
| 1 | `learnings.json` missing (run a session with Sylph installed first) |
