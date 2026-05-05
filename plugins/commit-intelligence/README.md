# commit-intelligence

**Drafts + validates Conventional Commits messages. Two-stage pipeline: Sonnet drafts, Haiku validates.**

Engine: **W1 — Myers-Diff Conventional Classifier.**

Takes the Myers-diff + `git status` + file paths; if the raw diff exceeds 1500 tokens, substitutes Crow V1's compressed form. Stage 1 (Sonnet) emits `type(scope)!: subject\n\nbody`. Stage 2 (Haiku) validates type, subject length, breaking-change marker vs exported-API paths, sign-off policy, body wrapping. Safe-amend detection blocks `git commit --amend` when the target has been pushed to any remote.

## Install

Part of the [Sylph](../..) bundle:

```
/plugin marketplace add enchanter-ai/sylph
/plugin install full@sylph
```

Standalone: `/plugin install commit-intelligence@sylph`. Without `boundary-segmenter`, commits must be developer-triggered via `/sylph commit` — the auto-orchestration flow breaks without W2.

## Components

| Type | Name | Role |
|------|------|------|
| Agent | commit-drafter (Sonnet) | W1 Stage 1 |
| Agent | message-validator (Haiku) | W1 Stage 2 |
| Command | `/sylph commit` | Manual invocation |
| Hook | PreToolUse(Bash) filter | Inspects `git commit` invocations |

## Hook chain

`commit-intelligence` registers a `PostToolUse(Edit|Write|MultiEdit)` hook (`hooks/post-tool-use/on-boundary.sh`) that tails `plugins/boundary-segmenter/state/boundary-events.jsonl` from its persisted byte offset in `state/listener-offset.json`. For each new `sylph.task.boundary.detected` line, it infers a Conventional-Commits type from the closed cluster's file paths and appends a `commit.drafted` record to `state/pending-drafts.jsonl`. The hook never calls an LLM — drafting happens when the developer invokes `/sylph:commit`, which reads pending drafts and hands them to the Sonnet commit-drafter agent.

Architecture note: **independent listener (Option 1)** — each plugin owns its own offset; the hook is advisory-only (exits 0 regardless).

## Cross-plugin

- **Consumes** `crow.change.classified` for V1 compressed-diff when diff > 1500 tokens.
- **Publishes** `sylph.commit.drafted`, `sylph.commit.committed`.

Full architecture: [../../docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md#layer-5-commit-intelligence-w1-myers-diff-conventional-classifier).
