---
name: reviewer-router
description: Explains how W4 Path-History Reviewer Routing ranks candidate reviewers — recency-weighted blame, path-depth specificity, CODEOWNERS boost, and optional Hornet reviewer-availability filtering. Helpful when a developer asks "why did Weaver suggest these reviewers?"
allowed-tools: Read
---

# reviewer-router

## The scoring function

For each candidate (git log author OR CODEOWNERS entry):

```
score = (sum over changed-paths of: recency_weight(last_commit) × path_depth_weight(path))
        × (1.5 if CODEOWNERS matched for any changed path else 1.0)
        × availability (0.0..1.0; default 1.0 when unknown)
```

Where:

- `recency_weight(ts) = exp(-age_days × ln(2) / 90)` — 90-day half-life.
- `path_depth_weight(path) = 1.0 + min(0.5, depth × 0.1)` — deeper paths
  are worth more than root-level changes, capped at 1.5×.

Top-K is capped by `WEAVER_REVIEWER_MAX_SUGGEST` (default 3) to avoid the
Kubernetes-style "review storm" anti-pattern.

## CODEOWNERS

Parsed from (in order): `.github/CODEOWNERS`, `CODEOWNERS`,
`docs/CODEOWNERS`. Weaver uses the GitHub CODEOWNERS glob dialect:

- `*` matches within a path segment
- `**` matches across segments
- leading `/` anchors to root
- trailing `/` matches directory + contents

Last matching entry wins (the spec's "most specific rule wins" is
implemented as "last matching line wins" per GitHub's actual behavior).

CODEOWNERS candidates are unioned with blame-graph candidates, not
merged on top. An @-handle from CODEOWNERS and a "Name <email>" from
blame can both be suggested — the PR adapter (W4) does de-dup at the
`gh pr create --reviewer` level.

## Availability (Hornet integration)

If Hornet is installed and publishes `hornet.reviewer.availability.changed`
events (availability ∈ [0.0, 1.0] per user), W4 multiplies the score by
availability before ranking.

Without Hornet, all candidates are assumed fully available (availability =
1.0). Weaver does not try to parse out-of-office signals from git logs or
calendar integrations.

## Why caps at 3

Kubernetes' early test-infra bot auto-assigned reviews to 8+ maintainers per
PR, fragmenting attention. They eventually shipped `OWNERS_ALIASES` +
randomized-subset selection. Weaver skips to the fix: cap at 3, rotate
across the larger eligible pool on subsequent PRs on the same paths
(rotation logic lives in W5 via `state/reviewer-history.jsonl`).

## When a developer overrides

`gh pr edit <n> --add-reviewer <handle>` is fine — W4's suggestion is a
suggestion. The `reviewer-history.jsonl` tracks overrides so W5 can learn
"this developer always adds @tech-lead regardless of blame" and adjust
future suggestions.

## Exit paths

- No candidates ranked: `/weaver:pr` proceeds with no reviewers; the PR
  opens as draft without assignments. Reviewers can be added manually.
- CODEOWNERS absent AND blame graph empty (new file): candidate pool is
  empty, ranking returns `[]`. That's fine for a genuinely new area.
