# Weaver

<p>
  <a href="LICENSE.txt"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-3fb950?style=for-the-badge"></a>
  <img alt="8 plugins" src="https://img.shields.io/badge/Plugins-8-bc8cff?style=for-the-badge">
  <img alt="10 git hosts" src="https://img.shields.io/badge/Hosts-10-58a6ff?style=for-the-badge">
  <img alt="8 CI systems" src="https://img.shields.io/badge/CI-8-d29922?style=for-the-badge">
  <img alt="Jaccard-Cosine W2" src="https://img.shields.io/badge/Jaccard--Cosine-W2-f0883e?style=for-the-badge">
</p>

> **An @enchanted-plugins product — algorithm-driven, agent-managed, self-learning.**

The git-workflow layer of AI-assisted development. Observes your Claude Code session, finds task boundaries, branches, commits, and draft-PRs — autonomously. Silent when it works, loud when you're about to break something.

**8 plugins. 5 named engines. 9 git hosts. 8 CI systems. One event bus.**

> You ask Claude to "refactor the auth module and add OAuth PKCE."
>
> Weaver watched the edits. W2 detected two task boundaries — one for the refactor, one for the PKCE addition. Each became its own branch, each its own signed Conventional Commit. Two draft PRs opened, each with a Hornet-V4 session-context body, reviewers routed by W4 from blame + Hornet availability. When Assembler signalled green CI, both promoted to ready and enqueued on the GitHub Merge Queue.
>
> Time: the duration of your session. Manual git operations: zero. Destructive ops invoked: zero (W2 never rewrites pushed history).

## Contents

- [How It Works](#how-it-works)
- [What Makes Weaver Different](#what-makes-weaver-different)
- [The Auto-Orchestration Flow](#the-auto-orchestration-flow)
- [Install](#install)
- [8 Plugins, 5 Engines, 9 Hosts, 8 CI Systems](#8-plugins-5-engines-9-hosts-8-ci-systems)
- [Destructive-Op Contract](#destructive-op-contract)
- [Ecosystem Interactions](#ecosystem-interactions)
- [Architecture](#architecture)
- [Contributing](#contributing)
- [License](#license)

## How It Works

<p align="center">
  <img src="docs/assets/highlevel.svg"
       alt="Weaver high-level: Claude Code tool calls route to capability-memory (SessionStart) and weaver-gate (PreToolUse) plus 7 more plugins coordinating through mcp-event-bus"
       width="100%" style="max-width: 900px;">
</p>

<details>
<summary>View all four diagrams (regenerated from plugin.json &amp; hooks.json)</summary>

- [High level](docs/assets/highlevel.svg) — plugins and the hook phases they own
- [Hook detail](docs/assets/hooks.svg) — which tool matchers fire which scripts with what timeouts
- [Data flow](docs/assets/dataflow.svg) — per-plugin metrics streams into mcp-event-bus
- [Session lifecycle](docs/assets/lifecycle.svg) — SessionStart → PreToolUse → PostToolUse → PreCompact

Regenerate after editing any `plugin.json` or `hooks.json`:

```bash
python docs/architecture/generate.py
npx -y -p @mermaid-js/mermaid-cli mmdc -i docs/architecture/highlevel.mmd \
  -o docs/assets/highlevel.svg -c docs/assets/mermaid.config.json -b "#0d1117" -w 1400
# ...repeat for hooks / dataflow / lifecycle
```

</details>

Weaver doesn't replace git. It *listens* to your session and drives git on your behalf.

Every `PostToolUse(Edit|Write)` event flows into **W2 — Jaccard-Cosine Boundary Segmentation**, an online clustering algorithm that decides when a coherent logical unit of work has completed. The distance function combines file-set Jaccard, Hornet-V1 semantic-diff cosine, and idle-time gap — multi-signal from day one, avoiding the idle-timer-only split failure mode Graphite hit in 2023.

When a boundary closes:
- **W3 — Workflow-Pattern Classifier** infers your branching model (GitHub Flow / Trunk-Based / GitFlow / Release Flow / Stacked Diffs) from repo signals and picks a branch name.
- **W1 — Myers-Diff Conventional Classifier** drafts a Conventional Commits message (Sonnet), then validates format + policy (Haiku).
- **W4 — Path-History Reviewer Routing** ranks reviewers from `git log` blame + CODEOWNERS + Hornet availability events, caps at 3.
- **weaver-gate** inspects every `git` invocation via `PreToolUse(Bash)` and routes destructive ops through a Hornet-style decision-gate.
- **capability-memory** encodes how each of the 9 git hosts actually behaves — rate limits, webhook signing, merge-queue support, CODEOWNERS flavor, known quirks.
- **ci-reader** reads status from 8 CI systems to gate merge-queue entry. **Weaver never triggers a build — that's Assembler's domain.** Ownership boundary enforced via the enchanted-mcp event bus.
- **W5 — Gauss Learning (Weaver)** persists your commit-style preferences across sessions (Allay-A4 atomic serialization).

## What Makes Weaver Different

### It covers every git host you actually use

**Tier-1 (first-class):** GitHub (Cloud + Enterprise Server), GitLab (SaaS + self-managed), Bitbucket Cloud, Bitbucket Data Center.

**Tier-2 (best-effort / read-only, explicit):** Azure DevOps, Gitea, Forgejo, Codeberg, AWS CodeCommit, SourceHut.

The Provider Capability Registry encodes each host's quirks as data — not branching code. GitHub's 5k-vs-15k rate-limit difference between PAT and App tokens, GitLab self-managed's v14+ capability drift, Bitbucket Cloud's unsigned webhooks, SourceHut's mailing-list PR workflow. The registry is the source of truth.

### It reads every CI system, it triggers none

Weaver **reads** GitHub Actions, GitLab CI, CircleCI, Jenkins, Buildkite, Drone/Woodpecker, Tekton, ArgoCD/FluxCD. Status reads gate PR merges. Triggers, builds, and deploys belong to Assembler (Phase 3 roadmap) — the boundary is enforced by the event bus.

### It's silent when it works, loud when it matters

Auto-orchestration is invisible when things go well. The decision-gate fires only for destructive ops — force-push, history rewrite, branch deletion, `clean -fdx`, merge-queue bypass. The audit log at `plugins/*/state/audit.jsonl` captures every gated operation.

### It learns from your corrections

W5 tracks which commit messages you accept, which you rewrite, which branch names you override. Over 6+ weeks of use, W1 and W3 adapt to your style. Accumulated learnings feed into the `shared/learnings.json` Gauss Accumulation network that connects to the rest of the enchanted-plugins ecosystem.

## The Auto-Orchestration Flow

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#auto-orchestration-flow) for the full 23-step sequence with latency budgets. The summary:

| Stage | Latency | What happens |
|---|---|---|
| Edit → Boundary | ~25ms | W2 clusters the event, decides same-cluster or boundary |
| Boundary → Commit | ~3.5s | Branch checkout, W1 Stage 1 (Sonnet), W1 Stage 2 (Haiku), sign, commit |
| Commit → Draft PR | ~6.5s | Push, Opus PR-description from Hornet V4, W4 reviewer routing, host-API POST |
| PR → Ready | event-driven | `assembler.pipeline.status.changed` promotes to ready on first green + approval |

## Install

```bash
/plugin marketplace add enchanted-plugins/weaver
/plugin install full@weaver
```

That installs all 8 plugins via the dependency resolution in `full`. Cherry-pick with e.g. `/plugin install commit-intelligence@weaver` if you want only W1.

Pre-flight: Weaver expects `git` on PATH and either `git-credential-manager` or `gh auth` configured. The installer warns if neither is present.

## 8 Plugins, 5 Engines, 9 Hosts, 8 CI Systems

| Plugin | Engine | Role |
|--------|--------|------|
| `commit-intelligence` | W1 — Myers-Diff Conventional Classifier | Drafts + validates Conventional Commits messages |
| `boundary-segmenter` | W2 — Jaccard-Cosine Boundary Segmentation | **Defining engine.** Clusters `PostToolUse(Edit\|Write)` into task boundaries |
| `branch-workflow` | W3 — Workflow-Pattern Classifier | Detects branching model, drives branch creation |
| `pr-lifecycle` | W4 — Path-History Reviewer Routing | PR state machine + reviewer ranking |
| `weaver-gate` | (rules) | Destructive-op decision-gate, Hornet pattern |
| `capability-memory` | (schema) | Provider capability registry — the host "memory" |
| `ci-reader` | (adapters) | Read-only status + log-stream across 8 CI systems |
| `weaver-learning` | W5 — Gauss Learning (Weaver) | Developer preference persistence, Allay-A4 atomic |
| `full` | (meta) | Declares the other 8 as dependencies |

## Destructive-Op Contract

Full table in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#destructive-op-confirmation-contract). Headline rules:

- **Protected-branch force-push** → never bypassed.
- **`git clean -fdx`** → never bypassed (irrecoverable).
- **Merge-queue `--admin` bypass** → never bypassed without explicit `--admin-bypass` flag.
- **All other destructive ops** → `--yes-i-know` bypass for one invocation, always audited.

## Ecosystem Interactions

Weaver is the 21st plugin in the @enchanted-plugins roadmap. Every cross-plugin interaction flows through the mcp-event-bus:

- **Hornet → Weaver**: V1 semantic-diff vectors, V4 session-continuity, reviewer availability.
- **Reaper → Weaver**: pre-push secret detection, dangerous-action blocks.
- **Weaver → Assembler**: CI trigger requests, PR state transitions.
- **Nook → Weaver**: budget-threshold signals driving Opus→Sonnet→Haiku degradation.
- **Weaver → Shared Learnings**: Gauss Accumulation network via W5.

Never direct imports across plugins. Events only.

## Architecture

Full architecture document at [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Produced by [flux/prompts/weaver-architecture/](https://github.com/enchanted-plugins/flux/tree/main/prompts/weaver-architecture) — σ=0.40, DEPLOY, all 12 success criteria verified.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). TL;DR: zero pip installs, honest scoring, per-sub-plugin structure identical, tests pass, Assembler boundary respected.

## License

MIT. See [LICENSE.txt](LICENSE.txt).
