---
name: sylph:reviewers
description: Rank candidate reviewers for the changed files on the current branch using W4 Path-History Reviewer Routing (blame × recency × CODEOWNERS × availability, capped at 3). Does NOT assign — shows the ranked list so you decide.
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/reviewer_route.py *), Bash(python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/reviewer_route.py *), Bash(git diff --name-only *), Bash(git log --format=*), Read(.github/CODEOWNERS), Read(CODEOWNERS), Read(docs/CODEOWNERS)
---

# /sylph:reviewers

Show the W4 reviewer ranking for the current branch's changes — without
actually assigning anyone.

## Usage

```
/sylph:reviewers                    # rank for `origin/main..HEAD`
/sylph:reviewers --base develop     # explicit base
/sylph:reviewers --paths a.py b.py  # rank for specific paths
/sylph:reviewers --max 5            # raise the cap from 3 (warning: storm-prone)
/sylph:reviewers --explain          # also show why each candidate was picked
```

## Output

Default (3 reviewers, scored):

```
@dave       score=2.84    blame + CODEOWNERS (src/auth/)    avail=1.0
@alice      score=1.67    blame (src/api/)                   avail=0.8
@ben        score=1.22    CODEOWNERS (docs/)                 avail=1.0
```

With `--explain`:

```
@dave — 2.84
  blame: 3 commits on src/auth/oauth.py (0.4d, 2.1d, 14d ago) — recency × path-depth = 2.41
  CODEOWNERS match: /src/auth/* → +1.5x boost
  availability: 1.0 (no Crow signal)

@alice — 1.67
  blame: 2 commits on src/api/routes.py (7d, 31d ago) — recency × path-depth = 1.67
  CODEOWNERS: no match
  availability: 0.8 (crow.reviewer.availability.changed at 2026-04-17)

@ben — 1.22
  ...
```

## Why this command is useful standalone

- You want a reviewer opinion without touching the PR state (no
  auto-assign, no API call, no notification).
- You're about to open a PR via web UI and want the suggestion to paste.
- You're debugging why `/sylph:pr` chose the reviewers it did.
- You want to cross-check against the CODEOWNERS you just edited.

## Flow

```
1. Resolve changed paths: `git diff --name-only origin/<base>...HEAD`
2. Parse CODEOWNERS from .github/CODEOWNERS, CODEOWNERS, docs/CODEOWNERS.
3. For each path: `git log --format='%an <%ae>' -- <path>` weighted by
   recency (90-day half-life) × path depth.
4. Score = blame × (1.5 if CODEOWNERS match else 1.0) × availability
   (from crow.reviewer.availability events when Crow is installed,
   else default 1.0).
5. Cap at SYLPH_REVIEWER_MAX_SUGGEST (default 3; --max overrides).
6. Print ranked list.
```

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Ranking produced (even if empty — e.g., new file with no blame) |
| 1 | Not in a git repo / no commits in range |
