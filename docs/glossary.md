# Sylph glossary

Terms of art used across Sylph. Short definitions; the algorithms live in [docs/science/README.md](science/README.md).

## Engines (W1–W5)

| ID | Name | Purpose |
|----|------|---------|
| W1 | Myers Diff | Textual diff with O(ND) complexity — the substrate every downstream engine reads. |
| W2 | Jaccard-Cosine | Change-similarity scoring across the session: how alike is this change to recent changes? |
| W3 | Workflow Classifier | Reads repo state (branches, commits, PRs, CI) and classifies the active workflow — trunk-based, gitflow, release-branch, feature-branch, stacked-diff. |
| W4 | Path-History | Reviewer suggestion: blame × CODEOWNERS × availability, capped at 3. |
| W5 | Gauss Learning | Per-developer EMA over observed preferences — commit style, review timing, revert patterns. |

Derivations in [docs/science/README.md](science/README.md).

## Workflow classes

The workflow classifier (W3) tags the active repo into one of these classes. Everything downstream — commit style, PR base, merge strategy, reviewer set — adapts to the classified workflow.

| Class | Signature | Typical merge strategy |
|-------|-----------|------------------------|
| **trunk-based** | Short-lived branches, single long-lived main, high-frequency merges. | Squash |
| **gitflow** | `develop` + `main`; release branches cut from develop; hotfixes merged to both. | Merge-commit |
| **release-branch** | Long-lived release branches alongside main; cherry-picks between them. | Merge-commit |
| **feature-branch** | Named feature branches, opened per task, merged into main. | Squash or Rebase |
| **stacked-diff** | Dependent PRs opened as a stack (Phabricator / Graphite style). | Rebase |
| **other** | Doesn't match a canonical class; Sylph defaults conservatively. | Merge-commit with confirmation |

Sylph never *forces* a classification. Every command that depends on class prints the detected class first; the user can override.

## H-suffix references

Some Sylph engines cite Crow's engines explicitly because Sylph reuses the pattern that Crow established for its pre-tool gate.

| H-suffix | Crow engine | Where Sylph uses it |
|----------|---------------|----------------------|
| H2 | Bayesian Trust | `sylph-gate` uses the same gate pattern: advisory-first, blast-radius honest, never silently blocks. |
| H5 | Adversarial Robustness | Hardening the decision-gate against "benign-looking destructive commands" (re-label exploits, typo'd flags) uses the H5 pattern. |
| H6 | Session Learning | W5 Gauss Learning shares the EMA update shape. |

The cross-ref isn't a dependency — Sylph runs standalone — it's an acknowledgement that the patterns originated in Crow and stay aligned.

## Conventional Commits shorthand

Sylph's `commit-intelligence` emits [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/). The short reference:

| Prefix | When to use |
|--------|-------------|
| `feat` | New user-visible capability. |
| `fix` | Bug fix. |
| `docs` | Documentation only. |
| `style` | Formatting / whitespace / style; no behavior change. |
| `refactor` | Code change that neither fixes a bug nor adds a feature. |
| `perf` | Performance improvement. |
| `test` | Adding or updating tests. |
| `build` | Changes to build system or external dependencies. |
| `ci` | CI-only changes. |
| `chore` | Miscellaneous maintenance. |
| `revert` | Revert of a previous commit. |

**Scope** is the sub-plugin slug for Sylph internal commits (e.g., `feat(pr-lifecycle): …`). For application repos Sylph is operating on, scope follows the local convention — if the repo uses module names, so does Sylph.

**Breaking changes** — append `!` after the type, or include a `BREAKING CHANGE:` footer. The classifier respects both.

## Destructive-op classification

`sylph-gate` classifies pre-tool Bash commands into four bands. Advisory only — per the hooks contract, the user or orchestrator decides.

| Band | Examples | Gate behavior |
|------|----------|---------------|
| **Terminal** | `rm -rf /`, `git push --force main`, `DROP TABLE`, `:wq!` on a protected file | Blast-radius summary + explicit confirmation ask. |
| **Hard-to-reverse** | `git reset --hard`, `git rebase -i`, branch delete, tag delete | Plan + confirmation. |
| **Shared-state** | Publishing to npm / PyPI, pushing to main, creating a release | State the target + confirmation. |
| **Local** | Anything else in the user's working tree | No gate. |

## CI systems recognized

Sylph's `ci-reader` is read-only across these systems: GitHub Actions, GitLab CI, Bitbucket Pipelines, Jenkins, CircleCI, Buildkite, TeamCity, Azure Pipelines, Drone, Woodpecker. It never *triggers* builds — Sylph is a git-workflow plugin; CI execution belongs to your existing CI pipelines.

## Git hosts recognized

`capability-memory` probes for: GitHub, GitLab (self-hosted + SaaS), Bitbucket, Gitea, Forgejo, Sourcehut, Codeberg, AWS CodeCommit, Azure Repos, Phabricator-compatible (diffusion).

## See also

- [README.md](../README.md) — what Sylph does end-to-end.
- [docs/getting-started.md](getting-started.md) — 5-minute first run.
- [docs/science/README.md](science/README.md) — derivations for W1–W5.
- [docs/architecture/](architecture/) — auto-generated diagram.
