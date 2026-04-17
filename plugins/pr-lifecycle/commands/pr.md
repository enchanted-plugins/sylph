---
name: weaver:pr
description: Open or update a draft PR for the current branch. Composes the description from W2 cluster state + Hornet V4 session-continuity (when available), ranks reviewers via W4 Path-History Reviewer Routing, dispatches to the host adapter (GitHub fully implemented; other hosts degrade to manual-handoff mode).
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/pr_lifecycle.py *), Bash(python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/pr_lifecycle.py *), Bash(gh pr *), Bash(git branch --show-current), Bash(git remote get-url *), Bash(git log *), Read(plugins/boundary-segmenter/state/boundary-clusters.json)
---

# /weaver:pr

Open or update a draft PR for the current branch.

## Usage

```
/weaver:pr                          # open draft PR (base = default branch)
/weaver:pr --base develop           # explicit base
/weaver:pr --head feature/xyz       # explicit head
/weaver:pr --ready                  # mark an existing PR ready for review
/weaver:pr --dry-run                # compose title + body + reviewer plan without network calls
```

## Flow

```
1. Resolve host via `shared/scripts/adapters` URL detection.
   ├─ github.com  → full flow via `gh` CLI
   ├─ gitlab/bitbucket/etc → degrade to manual-handoff (print plan, do not call API)
   └─ unknown → error out with hint

2. Resolve base / head.
   ├─ head = `git branch --show-current` unless --head given
   ├─ base = `git symbolic-ref refs/remotes/origin/HEAD` → "main"/"master"
   └─ if both match, abort with hint ("you're on the default branch")

3. Compose description.
   ├─ commits = `git log origin/base..head` (or base..head for first push)
   ├─ cluster = plugins/boundary-segmenter/state/boundary-clusters.json (W2 last closed)
   ├─ V4 continuity = plugins/hornet-session-memory/state/session-graph.json (optional)
   └─ Build title + "## What changed / ## Why / ## How verified / ## Rollback plan"

4. Rank reviewers via W4 (`shared/scripts/reviewer_route.py`).
   ├─ changed_paths = `git diff --name-only base...head`
   ├─ score = recency × path-depth × (1.5 if CODEOWNERS match else 1.0) × availability
   └─ top-3, capped by WEAVER_REVIEWER_MAX_SUGGEST

5. Dispatch.
   ├─ github adapter → `gh pr create --draft --reviewer ...`
   ├─ stub adapter  → print manual-handoff plan, exit with warning
   └─ publish weaver.pr.drafted event
```

## Graceful degradation

- **Hornet not installed** → description omits the "## Why" session-continuity
  block, uses commit messages only. Noted inline so reviewers know.
- **boundary-segmenter not installed** → description falls back to
  commit-subject as title, first changed file as slug.
- **`gh` CLI absent or not authenticated** → `--dry-run` output is printed and
  exit 2 with a setup hint. No blind `gh` calls.
- **Host not GitHub** → plan is printed; a `weaver.pr.manual_handoff.required`
  event goes to `state/metrics.jsonl` so the developer (or a future
  GitLab/Bitbucket adapter) can pick it up.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | PR opened / updated / dry-run printed |
| 1 | Adapter not authenticated (setup required) |
| 2 | Unknown host, manual handoff needed |
| 3 | Git error (no remote, no current branch, etc.) |
