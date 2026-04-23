---
name: pr-description-crafter
description: Explains how Sylph composes PR descriptions — the 4-section template, the fallback ladder when Raven V4 continuity or W2 cluster data is missing, and how to override the default template via PULL_REQUEST_TEMPLATE.md.
allowed-tools: Read
---

# pr-description-crafter

## The 4-section template

```
## What changed     — commit subjects, with short SHAs
## Why              — session intent (Raven V4) or inferred from commits
## How it was verified — observed test runs, or "inspection only"
## Rollback plan    — `git revert --no-commit <shas>` template
```

## Fallback ladder

Sylph produces the best description it can from whatever signals are present:

1. **Full signal** (Raven V4 installed + W2 active + commits present)
   → every section populated from distinct sources. Ideal state.
2. **No Raven V4** (most common today — Raven is Phase-1 shipping)
   → "Why" block notes the missing data and falls back to commit-subject
   synthesis.
3. **No W2 cluster** (user hasn't adopted auto-orchestration)
   → Title uses the last commit's subject; body uses commit list only.
4. **No commits** (rare — only if the branch has just been created)
   → Refuse; `/sylph:pr` aborts with a hint to commit first.

## Overriding

If the repo has a GitHub `.github/PULL_REQUEST_TEMPLATE.md`, Sylph honors
it by **appending** the four Sylph sections below the template. Developers
who want Sylph's sections to replace the template should delete the
template file; developers who want Sylph to defer entirely can set:

```yaml
# .sylph/config.yaml
pr_description:
  mode: template-only    # "template-only" | "append" (default) | "sylph-only"
```

[Not yet implemented — roadmap.]

## When to invoke this skill

- A developer asks "can I customize the PR body?"
- A PR description looks wrong and the developer wants to understand which
  signal was missing.
- Debugging why an Opus call for pr-description-crafter produced a thin body.

## Cost notes

The pr-description-crafter agent is Opus-tier. Each PR open costs ~1 Opus
call (typically 2k-6k input tokens, 500-1500 output). If Pech signals
budget pressure via `pech.budget.threshold.crossed`, Sylph degrades to
Sonnet (produces a serviceable but terser description) and tags the PR
body with a `*(budget-degraded)*` marker.
