# Contributing to Sylph

## Stack

Python 3.8+ (stdlib only) for scripts. Bash + jq for hooks. Markdown for skills, agents, and references. No external dependencies — `git-credential-manager` is the one recommended external tool and even that has a `gh auth` fallback.

## Critical Rules

Before submitting a PR, verify:

1. **Zero pip installs** — scripts use only Python stdlib. Tree-sitter is gated behind a `--deep-signals` opt-in flag and is not a default dep.
2. **SKILL.md uses `${CLAUDE_PLUGIN_ROOT}/../../shared/`** — never hardcoded paths.
3. **Provider capability registry stays current** — bump `last_updated` when adding a host or changing capabilities.
4. **Honest scoring** — W2 confidence, W4 reviewer ranks, and W5 learning deltas must report real numbers. Inflation breaks the Wixie-bred honest-numbers contract.
5. **Every sub-plugin has identical structure** — `agents/`, `commands/`, `hooks/`, `skills/`, `state/`. Run `bash tests/check-plugin-structure.sh` before pushing.
6. **Destructive-op gate covers new destructive ops** — if you add a new git invocation to any plugin, audit whether it can destroy reflog-unrecoverable state. If yes, it routes through `sylph-gate`.
7. **Tests pass** — `bash tests/run-all.sh` must exit 0.
8. **Build triggers not introduced — Sylph reads CI only.** No build-triggering code paths; CI execution belongs to your existing CI pipelines.

## Structure

```
sylph/
├── .claude-plugin/marketplace.json         Marketplace (8 plugins + full meta-plugin)
├── plugins/
│   ├── commit-intelligence/                W1 — Myers-Diff Conventional Classifier
│   ├── boundary-segmenter/                 W2 — Jaccard-Cosine Boundary Segmentation (defining)
│   ├── branch-workflow/                    W3 — Workflow-Pattern Classifier
│   ├── pr-lifecycle/                       W4 — Path-History Reviewer Routing
│   ├── sylph-gate/                        Destructive-op decision-gate (Crow pattern)
│   ├── capability-memory/                  Provider capability registry (the "memory")
│   ├── ci-reader/                          Read-only CI status across 8 systems
│   ├── sylph-learning/                    W5 — Gauss Learning (Sylph)
│   └── full/                               Meta-plugin — declares the other 8 as deps
├── shared/                                 Cross-plugin Python stdlib modules
├── configs/claude-code/                    Default Claude Code settings recommendations
├── docs/                                   ARCHITECTURE.md, brand, ecosystem
└── tests/                                  Per-plugin test suites + run-all.sh
```

Every plugin directory has:

```
plugins/<name>/
├── agents/     Opus/Sonnet/Haiku agent definitions (markdown with frontmatter)
├── commands/   Slash commands (markdown)
├── hooks/      hooks.json + per-event scripts (bash)
├── skills/     Skill markdown with frontmatter
└── state/      Runtime state (gitignored except .gitkeep)
```

## Named Engines

Every engine has a formal-algorithm-level name. "Smart commit generator" is not a name. "Myers-Diff Conventional Classifier" is. If you add an engine, name it after the algorithm it implements, not the feature it provides.

## Cross-Plugin Dependencies

Sylph plugins talk via the enchanted-mcp event bus, not direct imports. Cross-plugin logic belongs in event handlers.

- W2 consumes Crow V1 embeddings via `crow.change.classified`.
- W4 consumes Crow V4 session-continuity via `crow.session.continuity.node`.
- Pech cost pressure routes through `pech.budget.threshold.crossed`.

If you find yourself importing another plugin's module, stop — publish an event instead.

## Reviewer Suggestions

Sylph suggests its own reviewers via W4 once a PR is opened. Human maintainers of this repo (listed in CODEOWNERS) override. The first few PRs will have manual CODEOWNERS while W4 bootstraps on the blame graph.

## License

MIT. See [LICENSE.txt](LICENSE.txt).
