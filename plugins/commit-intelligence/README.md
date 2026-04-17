# commit-intelligence

**Drafts + validates Conventional Commits messages. Two-stage pipeline: Sonnet drafts, Haiku validates.**

Engine: **W1 — Myers-Diff Conventional Classifier.**

Takes the Myers-diff + `git status` + file paths; if the raw diff exceeds 1500 tokens, substitutes Hornet V1's compressed form. Stage 1 (Sonnet) emits `type(scope)!: subject\n\nbody`. Stage 2 (Haiku) validates type, subject length, breaking-change marker vs exported-API paths, sign-off policy, body wrapping. Safe-amend detection blocks `git commit --amend` when the target has been pushed to any remote.

## Install

Part of the [Weaver](../..) bundle:

```
/plugin marketplace add enchanted-plugins/weaver
/plugin install full@weaver
```

Standalone: `/plugin install commit-intelligence@weaver`. Without `boundary-segmenter`, commits must be developer-triggered via `/weaver commit` — the auto-orchestration flow breaks without W2.

## Components

| Type | Name | Role |
|------|------|------|
| Agent | commit-drafter (Sonnet) | W1 Stage 1 |
| Agent | message-validator (Haiku) | W1 Stage 2 |
| Command | `/weaver commit` | Manual invocation |
| Hook | PreToolUse(Bash) filter | Inspects `git commit` invocations |

## Cross-plugin

- **Consumes** `hornet.change.classified` for V1 compressed-diff when diff > 1500 tokens.
- **Publishes** `weaver.commit.drafted`, `weaver.commit.committed`.

Full architecture: [../../docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md#layer-5-commit-intelligence-w1-myers-diff-conventional-classifier).
