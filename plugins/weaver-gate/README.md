# sylph-gate

**Destructive-op advisory. Crow's pattern, Sylph's domain.**

Inspects every `git` invocation via `PreToolUse(Bash)`. If the command matches a destructive-op pattern (force-push, `filter-branch`, `reset --hard` past pushed tip, `branch -D`, `tag -d`, `clean -fdx`, remote-branch deletion, `commit --amend` of a pushed HEAD, merge-queue `--admin` bypass), the gate **WARNS** about the operation via a stderr advisory — it **never blocks**. The model reads the advisory and decides whether to proceed, optionally routing through the `destructive-gate-confirmation` skill for explicit confirmation.

**Advisory contract.** Per [shared/conduct/hooks.md](../../shared/conduct/hooks.md): hooks inform, they don't decide. The hook always exits 0. Blocking semantics, when needed, live in a Skill the model invokes deliberately.

No engine — rules-only. Haiku classifies destructive vs safe per the pattern table. Protected-branch force-push: **never** bypassed. `git clean -fdx`: **never** bypassed (irrecoverable — reflog doesn't cover ignored files).

## Destructive-pattern table

All entries below trigger a stderr advisory only — the gate warns, the model decides. Bypass column is now historical context for the `destructive-gate-confirmation` skill, not the hook.

| Pattern ID | Matches | Severity | Confirmation guidance | Notes |
|------------|---------|----------|-----------------------|-------|
| `force_push` | `git push --force` / `-f` | destructive | `--yes-i-know` (one-shot) | Especially risky on protected branches |
| `force_with_lease` | `git push --force-with-lease` | destructive | `--yes-i-know` | Especially risky on protected branches |
| `filter_branch` | `git filter-branch` / `filter-repo` | destructive | `--yes-i-know` | History rewrite |
| `reset_hard` | `git reset --hard` | destructive | `--yes-i-know` | Reflog covers 90d |
| `rebase_interactive` | `git rebase -i` / `--interactive` | destructive | `--yes-i-know` | History rewrite when pushed |
| `branch_delete` | `git branch -D` | destructive | `--yes-i-know` | Reflog covers 90d |
| `remote_branch_delete` | `git push --delete <branch>` | destructive | `--yes-i-know` | Host retention varies |
| `tag_delete` | `git tag -d` | destructive | `--yes-i-know` | Remote delete is permanent |
| `clean_fdx` | `git clean -fdx` / `-fdX` | protected-destructive | irrecoverable | Reflog does not cover ignored files — the advisory flags this loudly |
| `amend_of_pushed_head` | `git commit --amend` when HEAD is reachable from a remote-tracking ref | destructive | `--yes-i-know` | Closes anti-pattern #2 (CLAUDE.md). Context-checked via `amend_safety.is_head_pushed` — amend on an unpushed branch is safe |

## Install

Part of the [Sylph](../..) bundle. **Installing Sylph without sylph-gate is not supported** — it's the safety floor.

```
/plugin marketplace add enchanted-plugins/sylph
/plugin install full@sylph
```

## Components

| Type | Name | Role |
|------|------|------|
| Hook | PreToolUse(Bash) | Primary inspection point |
| Skill | destructive-gate-confirmation | Decision surface |
| State | audit.jsonl | Append-only, Emu-A4 atomic pattern |

## Cross-plugin

- **Consumes** `hydra.action.dangerous` (blocks Sylph ops when Hydra flags the session).
- **Publishes** `sylph.destructive.detected`, `sylph.destructive.confirmed`, `sylph.destructive.cancelled`.

Full architecture: [../../docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md#destructive-op-confirmation-contract).
