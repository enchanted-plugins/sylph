# Getting started with Sylph

Sylph is the git-workflow layer above git. It knows which host you're on (10 supported), which CI runs there (10 supported), classifies your workflow, gates destructive operations, suggests reviewers, and learns your preferences over time. This page gets you from zero to a first commit through Sylph in under 5 minutes.

## 1. Install (60 seconds)

```
/plugin marketplace add enchanted-plugins/sylph
/plugin install full@sylph
/plugin list
```

You should see eight Sylph sub-plugins including `capability-memory`, `sylph-gate`, `boundary-segmenter`, `branch-workflow`, `pr-lifecycle`, `commit-intelligence`, `ci-reader`, and `sylph-learning`. If any are missing, see [installation.md](installation.md).

## 2. One-time setup

```
/setup
```

`capability-memory` probes your environment: git host, auth state, CI integration, provider registry. Answers are cached so subsequent commands don't re-probe.

## 3. Detect your workflow

```
/workflow-detect
```

W3 Workflow Classifier reads your repo state (branches, commits ahead/behind, open PRs, CI status) and classifies the workflow class — trunk-based, gitflow, release-branch, feature-branch, stacked-diff, etc. Everything downstream tailors itself to the classified workflow.

## 4. Commit with intelligence

Instead of `git commit -m`:

```
/commit
```

`commit-intelligence` inspects staged changes, generates a conventional-commits message scoped to the sub-plugin, and asks for confirmation. W1 Myers-Diff + W2 Jaccard-Cosine pick the right scope and verb.

## 5. Open a PR

```
/pr
```

`pr-lifecycle` opens a PR targeting the workflow-appropriate base, writes the body from the commit log, and suggests reviewers via W4 Path-History (blame × CODEOWNERS × availability, capped at 3).

Monitor it:

```
/status      PR status + CI at a glance
/ci-status   CI-only view, cross-system
```

Retry a flaky CI run:

```
/retry-ci
```

## 6. The decision gate

Destructive operations route through `sylph-gate`. A `git push --force`, a `git reset --hard`, a branch delete — all intercepted at PreToolUse. The gate is modeled on the Crow pattern: advisory-first, honest about blast radius, never silently blocks. Decline, and the command is gone.

Dry-run any staged operation:

```
/dry-run
```

## 7. Per-developer learning

```
/learnings
```

`sylph-learning` (W5 Gauss EMA) stores your per-developer preferences — commit-message style, review timing, revert patterns. It gets quieter as it learns what you already know.

## 8. Close the loop

```
/merge       Merge the PR through the classified workflow (squash, rebase, merge-commit, or stack).
/release     Tag + changelog update via conventional-commits.
/revert      Safe revert with context preservation.
```

## Next steps

- [Glossary](glossary.md) — workflow classes, H-suffix cross-refs, conventional-commits shorthand defined.
- [docs/science/README.md](science/README.md) — Myers-Diff, Jaccard-Cosine, Workflow Classifier, Path-History, Gauss Learning — derived.
- [docs/architecture/](architecture/) — auto-generated diagram of the 8-plugin surface.

Broken first run? → [troubleshooting.md](troubleshooting.md).
