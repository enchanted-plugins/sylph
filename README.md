# Weaver

<p>
  <a href="LICENSE.txt"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-3fb950?style=for-the-badge"></a>
  <img alt="8 plugins" src="https://img.shields.io/badge/Plugins-8-bc8cff?style=for-the-badge">
  <img alt="10 git hosts" src="https://img.shields.io/badge/Hosts-10-58a6ff?style=for-the-badge">
  <img alt="10 CI systems" src="https://img.shields.io/badge/CI-10-d29922?style=for-the-badge">
  <img alt="15 slash commands" src="https://img.shields.io/badge/Commands-15-f0883e?style=for-the-badge">
  <img alt="5 named engines (W1-W5)" src="https://img.shields.io/badge/Engines-W1--W5-ff7b72?style=for-the-badge">
  <img alt="28 tests passing" src="https://img.shields.io/badge/Tests-28%2F28-3fb950?style=for-the-badge">
  <img alt="Zero runtime deps (bash plus jq plus Python stdlib)" src="https://img.shields.io/badge/Deps-0-f85149?style=for-the-badge">
</p>

> **An @enchanted-plugins product — algorithm-driven, agent-managed, self-learning.**

**8 plugins. 5 named engines. 10 git hosts. 10 CI systems. 15 slash commands. Zero runtime deps.**

Built from the commit log of teams that ship: every flow exists because someone, somewhere, force-pushed their career off the edge.

---

> You edit three files. Weaver watches via `PostToolUse(Edit|Write)`.
>
> **W2** clusters the edits — file-set Jaccard + Hornet-V1 cosine + idle-gap — and fires a task boundary at distance 0.81 (threshold 0.55).
> **W3** classifies the repo as github-flow from the branch graph + protection rules + tag cadence. Creates `feat/oauth-pkce-verify`.
> **W1** (Sonnet) drafts a Conventional Commits message: `feat(auth): add OAuth PKCE verify`. Haiku + Python validate: 72-char subject ✓, canonical type ✓, body under 72-char wrap ✓. Signed with SSH, DCO sign-off appended.
> `git push -u origin feat/oauth-pkce-verify`. weaver-gate inspects — safe push, no block.
> Opens a draft PR against main. Body composed from the W2 cluster + commits + Hornet V4 session continuity: "What changed", "Why", "How it was verified", "Rollback plan".
> **W4** ranks reviewers from `git log` blame × recency × CODEOWNERS × Hornet availability. Top-3 requested: @dave (blame + CODEOWNERS), @alice (blame), @ben (CODEOWNERS).
> Subscribes to Assembler's pipeline-status events. When all required checks go green, auto-enqueues on the GitHub Merge Queue.
> **W5** records: scope "auth" seen, slug-style kebab confirmed, W4's top pick accepted.
>
> You typed **0** git commands. Zero destructive ops triggered. Commits signed. PR reviewed and merged.

Weaver is the git workflow layer you wrote yourself, if you'd had three months and a production-incident scar.

---

## Origin

Weaver takes its name from the **Weavers of Hollow Knight** — Hornet's ancestral kin, silk-spinners who wove threads into coherent patterns. Every branch is a thread; every merge stitches threads into history; every PR asks *does this fit the pattern?*

The question this plugin answers: *How does this ship?*

## Contents

- [The Numbers](#the-numbers)
- [How It Works](#how-it-works)
- [What Makes Weaver Different](#what-makes-weaver-different)
- [The Full Lifecycle](#the-full-lifecycle)
- [Install](#install)
- [What You Get Per Session](#what-you-get-per-session)
- [The Science Behind Weaver](#the-science-behind-weaver)
- [All 15 Workflows](#all-15-workflows)
- [10 Git Hosts, All Real](#10-git-hosts-all-real)
- [10 CI Systems, All Real](#10-ci-systems-all-real)
- [The Decision-Gate Contract](#the-decision-gate-contract)
- [Verification](#verification)
- [vs Everything Else](#vs-everything-else)
- [Agent Conduct (10 Modules)](#agent-conduct-10-modules)
- [Architecture](#architecture)
- [Contributing](#contributing)
- [License](#license)

## The Numbers

| | Count |
|---|---|
| Plugins | 8 (+ `full` meta) |
| Named algorithms | 5 (W1–W5) |
| Git hosts supported | 10 |
| CI systems supported | 10 |
| Slash commands | 15 |
| Destructive-op patterns classified | 10 |
| Agents (Opus / Sonnet / Haiku) | 5 |
| Test assertions | 28 passing |
| Live-tested hosts | 1 (GitHub — opened + round-tripped + closed a real PR) |
| Runtime dependencies | **0** (bash + jq + Python stdlib; `git-credential-manager`/`gh`/`aws`/`kubectl` are opt-in per adapter) |

---

## How It Works

Weaver runs inside your Claude Code session and drives git on your behalf:

- **Watches every edit.** PostToolUse hooks feed W2 Jaccard-Cosine boundary segmentation. Logical tasks get clustered automatically.
- **Scaffolds branches.** W3 detects your workflow (GitHub Flow / Trunk-Based / GitFlow / Release Flow / Stacked Diffs) and names branches to match (`feat/x`, `feature/x`, `user/x`, bare-topic).
- **Drafts commits.** W1 Sonnet drafts a Conventional Commits message; Haiku + Python stdlib validate format + policy; SSH/GPG signed; DCO sign-off if the repo wants it.
- **Opens PRs.** W4 ranks reviewers (blame × recency × CODEOWNERS × availability), composes a 4-section body from W2 cluster + Hornet V4 continuity, dispatches to the right host adapter.
- **Reads CI.** ci-reader normalizes check runs from 10 systems. Never triggers a build itself (that's Assembler's lane).
- **Merges.** Strategy inferred from workflow; merge-queue-enqueues where configured.
- **Guards destructive ops.** weaver-gate intercepts `PreToolUse(Bash)` — force-push / filter-branch / clean -fdx / rebase-i-of-pushed etc. route through a Hornet-style decision-gate before they can run.
- **Learns.** W5 Gauss EMA adapts priors per-developer. Past sample 10, the defaults give way to what you actually do.

<p align="center">
  <a href="docs/assets/pipeline.mmd" title="View pipeline source (Mermaid)">
    <img src="docs/assets/pipeline.svg"
         alt="Weaver nine-subplugin architecture blueprint — Claude Code session input, boundary-segmenter (W2, defining engine), commit-intelligence + branch-workflow + pr-lifecycle (W1+W3+W4), weaver-gate + capability-memory + ci-reader + weaver-learning (W5) support row, enchanted-mcp bus events, and peer-plugin reaction legend"
         width="100%" style="max-width: 1100px;">
  </a>
</p>

<sub align="center">

Source: [docs/assets/pipeline.mmd](docs/assets/pipeline.mmd) · Regeneration command in [docs/assets/README.md](docs/assets/README.md).

</sub>

## What Makes Weaver Different

### It clusters the edit stream, not the commit stream

W2 Jaccard-Cosine Boundary Segmentation runs on `PostToolUse(Edit|Write)` — *before* commits exist. Distance `= α·(1−jaccard(files)) + β·(1−cosine(tokens)) + γ·tanh(idle/τ)`. At θ=0.55, a coherent task closes and the commit+PR logic fires. No timer-based batching, no manual `git add` discipline — just "did I finish a logical thing?"

### Every git host speaks the same contract

10 hosts, 1 `HostAdapter` contract: token resolution → authenticated request → normalized `PullRequest` return. Same `_rest.api_request` call path for GitHub, GitLab, Bitbucket Cloud / Data Center, Azure DevOps, Gitea, Forgejo, Codeberg, AWS CodeCommit, and SourceHut. When one host's JSON shape changes, exactly one file moves.

### Destructive ops route through a Hornet-style gate

`git push --force`, `git rebase -i <pushed-ref>`, `git clean -fdx`, `git filter-branch` — every destructive pattern routes through weaver-gate before it can run. Recovery windows documented per op; `clean -fdx` has zero; force-push to protected branches has zero bypass. No accidental career-enders.

### It learns per-developer, not per-repo

W5 Gauss Learning EMA runs per `(developer, surface)`. After 10 samples, the defaults give way to what you actually do — commit-subject verbosity, kebab vs. snake branch-name preferences, reviewer override patterns, W2 threshold corrections.

## The Full Lifecycle

A tool call flows through Weaver in five stages top-to-bottom: **SessionStart** (Haiku) loads the provider registry via `capability-memory`; **PreToolUse(Bash)** (Haiku) gates destructive ops via `weaver-gate`; **PostToolUse(Edit|Write)** (Sonnet) clusters edits via W2 Jaccard-Cosine boundary segmentation; on boundary close, the **commit + PR** stage (Sonnet) runs W3/W1/W4 to auto-branch, auto-commit, and open a draft PR with ranked reviewers; **PreCompact** (Sonnet) persists developer preferences via W5 Gauss Learning. The orthogonal `ci-reader` poll feeds W4's merge-queue gate.

<p align="center">
  <a href="docs/assets/lifecycle.mmd" title="View lifecycle source (Mermaid)">
    <img src="docs/assets/lifecycle.svg"
         alt="Weaver session lifecycle blueprint — 5 stages: SessionStart (capability-memory), PreToolUse/Bash (weaver-gate), PostToolUse/Edit|Write (boundary-segmenter W2), Commit+PR (branch-workflow W3 + commit-intelligence W1 + pr-lifecycle W4), PreCompact (weaver-learning W5), plus orthogonal ci-reader poll feeding W4's merge-queue gate"
         width="100%" style="max-width: 1100px;">
  </a>
</p>

<sub align="center">

Source: [docs/assets/lifecycle.mmd](docs/assets/lifecycle.mmd) · Regeneration command in [docs/assets/README.md](docs/assets/README.md).

</sub>

---

## Install

Two commands in Claude Code + one per project:

```
/plugin marketplace add enchanted-plugins/weaver
/plugin install full@weaver
```

Then, from inside the repo you want to use Weaver on:

```
/weaver:setup
```

`/weaver:setup` is the **auto-configurator**: it runs `git remote get-url origin`, maps the URL to one of the 10 supported hosts, and does **only** the work that host needs — auto-installing the right tool via your platform's package manager (`winget` on Windows, `brew` on macOS, `apt`/`dnf`/`pacman` on Linux) and walking you through exactly one token prompt when required. No manual shell steps. No forced `gh` install if you're on GitLab.

If you skip setup entirely, Weaver runs in degraded mode — commit drafting + W2 task-boundary clustering + the destructive-op gate all work without any host credentials. Only PR opening / merging needs the host token.

<details>
<summary>What `/weaver:setup` does per host</summary>

| Host | What gets configured |
|---|---|
| GitHub | Uses the existing git-credential-manager token if present (the same one that authorizes `git push`). Otherwise offers to install `gh` + run `gh auth login`. |
| GitLab | Prompts for a PAT (api + write_repository scopes), stores via `git credential approve`. Handles self-managed via prompted api_base. |
| Bitbucket Cloud | Prompts for a Repository Access Token (App Passwords are deprecated). |
| Bitbucket Data Center | Prompts for api_base + HTTP PAT. |
| Azure DevOps | Prompts for PAT (Code + Pull Request scopes), org, project. |
| Gitea / Forgejo / Codeberg | Prompts for api_base + PAT. |
| AWS CodeCommit | Auto-installs `aws` CLI if missing; runs `aws configure` if no IAM identity resolves. |
| SourceHut | Configures the project's mailing-list address + `git send-email` OR SMTP credentials. |

</details>

---

## What You Get Per Session

```
plugins/boundary-segmenter/state/
├── boundary-clusters.json           W2 rolling cluster state, survives compaction
└── boundary-events.jsonl            Every fired task boundary, append-only

plugins/weaver-gate/state/
└── audit.jsonl                      Every gated/blocked destructive op

plugins/capability-memory/state/
└── capability-registry.json         10-host capability data, nightly-refreshed

plugins/weaver-learning/state/
├── learnings.json                   W5 EMA priors, cross-session
└── priors.json                      Session-cached slice downstream engines read

plugins/commit-intelligence/state/
└── metrics.jsonl                    Per-commit W1 classification metrics

plugins/pr-lifecycle/state/
└── last-reviewer-suggestion.json    W4's last blame-graph reviewer ranking
```

Everything event-sourced, JSONL where applicable, atomic where writes matter (Allay-A4 tempfile + rename + fsync). All state dirs gitignored; `.gitkeep` sentinels only.

---

## The Science Behind Weaver

| ID | Name | What it does | Algorithm |
|----|------|--------------|-----------|
| W1 | Myers-Diff Conventional Classifier | Drafts + validates Conventional Commits messages | Myers diff → rule-based classifier → LLM re-rank (Sonnet) + rules check (Haiku + Python) |
| W2 | Jaccard-Cosine Boundary Segmentation | Finds task boundaries in the edit stream | Online agglomerative clustering with multi-modal distance: α·(1−jaccard(files)) + β·(1−cosine(tokens)) + γ·tanh(idle/τ). α=β=0.4, γ=0.2, τ=300s, θ=0.55 |
| W3 | Workflow-Pattern Classifier | Detects GitHub Flow / Trunk-Based / GitFlow / Release Flow / Stacked Diffs | Weighted decision tree over branch-age distribution, protection rules, config-file markers, tag cadence. Per-subtree overrides via `.weaver/workflow-map.yaml` |
| W4 | Path-History Reviewer Routing | Ranks reviewers for a PR | Blame-graph scoring × recency (90-day half-life) × path-depth × CODEOWNERS boost × availability. Capped at 3 — no review storms |
| W5 | Gauss Learning (Weaver) | Per-developer preference adaptation | Exponential moving averages (α=0.3) over commit style, slug style, reviewer overrides, W2 corrections. Bootstrap floor at 10 samples |

Every engine has a formal-algorithm-level name. "Smart commit helper" is not a name. "Myers-Diff Conventional Classifier" is.

---

## All 15 Workflows

Everything a team does with git/PR/CI — wired through real host + CI adapters.

### Commits & branching

- **`/weaver:commit`** — draft + validate + sign + commit staged changes
- **`/weaver:branch`** — create a branch named per the detected workflow
- **`/weaver:workflow-detect`** — show W3's classification + rationale
- **`/weaver:revert`** — safe revert via new commit (never rewrites history)

### Pull requests

- **`/weaver:pr`** — open or update a draft PR with W2-cluster body + W4 reviewers
- **`/weaver:status`** — aggregate view of branch + commits + PR + CI + reviewers + merge queue
- **`/weaver:reviewers`** — rank reviewers without assigning (useful for web-UI workflows)
- **`/weaver:merge`** — merge with strategy inferred from workflow, or enqueue on a merge queue
- **`/weaver:close`** — close a PR without merging (for abandoned / superseded work)
- **`/weaver:release`** — tag + changelog + handoff to semantic-release / release-please / changesets / goreleaser

### CI & safety

- **`/weaver:ci-status`** — aggregate CI status across every configured system
- **`/weaver:retry-ci`** — rerun failing checks (existing runs only — new-build triggers are Assembler's lane)
- **`/weaver:dry-run`** — preview any git command through the destructive-op classifier without executing

### Learning

- **`/weaver:learnings`** — show W5 priors: commit style, slug style, reviewer overrides, W2 corrections

Every command has a markdown contract in `plugins/<name>/commands/*.md` — agents follow it; Claude Code dispatches the tools.

---

## 10 Git Hosts, All Real

No stubs. Every host has a full `HostAdapter` implementation. When credentials aren't configured, `is_authenticated()` returns False and ops raise `NotImplementedHostOp` cleanly — never silently fabricating a fake PR.

| Host | Transport | Auth | Status |
|------|-----------|------|--------|
| **GitHub** (Cloud + Enterprise) | urllib + gh fallback | `GH_TOKEN` / `GITHUB_TOKEN` / git-credential-manager | Live-tested end-to-end |
| **GitLab** (SaaS + self-managed) | urllib | `GITLAB_TOKEN` / `GL_TOKEN` | Contract-tested |
| **Bitbucket Cloud** | urllib (REST 2.0) | `BITBUCKET_TOKEN` | Contract-tested |
| **Bitbucket Data Center** | urllib (REST 1.0, version-based PUTs) | `BITBUCKET_DC_TOKEN` | Contract-tested |
| **Azure DevOps** | urllib (Basic-wrapped PAT, api-version=7.1) | `AZURE_DEVOPS_TOKEN` / `VSTS_TOKEN` | Contract-tested |
| **Gitea** | urllib (GH-shape, `token` header) | `GITEA_TOKEN` | Contract-tested |
| **Forgejo** | urllib (subclass of Gitea) | `FORGEJO_TOKEN` / `GITEA_TOKEN` | Contract-tested |
| **Codeberg** | urllib (forgejo.codeberg.org) | `FORGEJO_TOKEN` / git-credential-manager | Contract-tested |
| **AWS CodeCommit** | `aws codecommit` CLI | AWS CLI config / IAM | Contract-tested |
| **SourceHut** | `git format-patch` + smtplib | SMTP / `git send-email` config | Contract-tested |

Every adapter follows the same contract: token resolution → authenticated request → normalized `PullRequest` return. The only structural difference is SourceHut, whose "PR" is an email thread to a mailing list — Weaver generates and sends the patch series; review happens in-list.

---

## 10 CI Systems, All Real

Same pattern: every CI adapter reads status via its native API (HTTP for most, `kubectl` for k8s-native). Returns a normalized `Check` list — empty when credentials/tooling are absent, never fabricated. Weaver reads; **Assembler runs.**

| System | Transport | Gate-ready? |
|--------|-----------|-------------|
| GitHub Actions | urllib + gh (check-runs API) | Yes |
| GitLab CI | urllib (`/projects/:id/pipelines/:n/jobs`) | Yes |
| CircleCI | urllib (`Circle-Token` header) | Yes |
| Jenkins | urllib Basic auth, **treats UNSTABLE as failure** | Yes (with caveat) |
| Buildkite | urllib (SaaS control plane + agents) | Yes |
| Drone / Woodpecker | urllib (`/builds` or `/pipelines`) | Yes |
| Tekton | kubectl → PipelineRun CRDs | Yes (with kube access) |
| ArgoCD | kubectl → Application sync/health | Read-only (GitOps — drift surface) |
| FluxCD | kubectl → Kustomization Ready conditions | Read-only (GitOps) |

Jenkins gets its own note: **UNSTABLE is NOT success.** We learned that from the semantic-release / Jenkins incident where `status:SUCCESS` returned for a pipeline with `result:UNSTABLE` on a deploy stage. Weaver's Jenkins adapter requires `status == SUCCESS && result == SUCCESS` — anything else is non-green.

---

## The Decision-Gate Contract

Every destructive git operation routes through weaver-gate before it can run:

| Operation | Classification | Recovery window | Bypass |
|-----------|----------------|-----------------|--------|
| `git push --force` | Destructive | 30d (remote reflog) | `--yes-i-know` |
| `git push --force-with-lease` to protected branch | **Protected-destructive** | 30d | **Never** |
| `git rebase -i <pushed-ref>` | Destructive | 90d (local reflog) | `--yes-i-know` |
| `git filter-branch` / `filter-repo` | Destructive | 90d local / permanent remote | `--yes-i-know` + 5s countdown |
| `git reset --hard <past-pushed>` | Destructive | 90d | `--yes-i-know` |
| `git branch -D <unmerged>` | Destructive | 90d | `--yes-i-know` |
| `git push --delete <branch>` | Destructive | host-dependent (GitHub: 14d) | `--yes-i-know` |
| `git tag -d` | Destructive | 90d local / permanent remote | `--yes-i-know` |
| **`git clean -fdx`** | **Protected-destructive** | **0 (irrecoverable)** | **Never** |
| Merge-queue `--admin` bypass | Destructive | 0 (immediate) | `--admin-bypass` flag only |

Every gated op is audited to `plugins/weaver-gate/state/audit.jsonl` — append-only, Allay-A4 atomic write.

---

## Verification

- **28 test assertions** passing (`bash tests/run-all.sh`) — unit, contract, and integration tiers. JSON validation, bash syntax check, Python functional smoke, end-to-end hook simulation.
- **1 live integration test** (`WEAVER_INTEGRATION=1 bash tests/run-all.sh`) — creates a real branch on `enchanted-plugins/weaver`, opens a real draft PR via the urllib adapter path (no `gh` required), round-trips it via `get_pr`, closes it, deletes the branch. Proven against real GitHub.
- **Contract test for every host** (`tests/pr-lifecycle/test-all-hosts-contract.sh`) — asserts every one of the 10 adapters instantiates cleanly, reports a bool `is_authenticated`, and refuses to fabricate a PR when credentials are absent.
- **Honest numbers.** What's verified live: GitHub only. What's verified by contract: all 10 hosts + 10 CI systems. The README doesn't pretend otherwise. When you drop a GitLab/Bitbucket/Azure token in, you're using the same `_rest.api_request` call path that shipped through GitHub's real API. If something breaks there, it's in the per-host JSON shape, not the flow.

---

## vs Everything Else

| | Husky | pre-commit | commitizen | Graphite | `gh` alone | **Weaver** |
|---|---|---|---|---|---|---|
| Works without `node_modules` | ✗ | ✓ | ✓ | ✗ | ✓ | ✓ |
| Conventional Commits drafting | ✗ | ✗ | manual | ✗ | ✗ | **Sonnet draft + Haiku validate** |
| Task boundary detection | ✗ | ✗ | ✗ | timer only | ✗ | **W2 multi-signal (Jaccard + cosine + idle)** |
| Branch workflow detection | ✗ | ✗ | ✗ | GitHub Flow assumed | ✗ | **W3 per-subtree classifier** |
| Reviewer routing | ✗ | ✗ | ✗ | CODEOWNERS only | manual | **W4 blame × CODEOWNERS × availability, capped at 3** |
| Per-developer learning | ✗ | ✗ | ✗ | ✗ | ✗ | **W5 Gauss EMA** |
| Force-push gate | ✗ | ✗ | ✗ | ✗ | ✗ | **Hornet-pattern decision-gate** |
| Multi-host | github-only | any | any | github+gitlab | github-only | **10 hosts** |
| Multi-CI | n/a | n/a | n/a | n/a | github-only | **10 systems** |
| Zero runtime deps | ✗ npm | ✓ python | ✗ npm | ✗ node | ✓ | ✓ |

Weaver isn't replacing git. It's **the layer above it** that you were building piece-by-piece in every project anyway.

---

## Agent Conduct (10 Modules)

Every skill inherits a reusable behavioral contract from [shared/conduct/](shared/conduct/) — loaded once into [CLAUDE.md](CLAUDE.md), applied across all plugins. This is how Claude *acts* inside Weaver: deterministic, surgical, verifiable. Not a suggestion; a contract.

| Module | What it governs |
|--------|-----------------|
| [discipline.md](shared/conduct/discipline.md) | Coding conduct: think-first, simplicity, surgical edits, goal-driven loops |
| [context.md](shared/conduct/context.md) | Attention-budget hygiene, U-curve placement, checkpoint protocol |
| [verification.md](shared/conduct/verification.md) | Independent checks, baseline snapshots, dry-run for destructive ops |
| [delegation.md](shared/conduct/delegation.md) | Subagent contracts, tool whitelisting, parallel vs. serial rules |
| [failure-modes.md](shared/conduct/failure-modes.md) | 14-code taxonomy for `state/learnings.json` so W5 Gauss Accumulation compounds |
| [tool-use.md](shared/conduct/tool-use.md) | Tool-choice hygiene, error payload contract, parallel-dispatch rules |
| [formatting.md](shared/conduct/formatting.md) | Per-target format (XML / Markdown sandwich / minimal / few-shot), prefill + stop sequences |
| [skill-authoring.md](shared/conduct/skill-authoring.md) | SKILL.md frontmatter discipline, discovery test |
| [hooks.md](shared/conduct/hooks.md) | Advisory-only hooks, injection over denial, fail-open |
| [precedent.md](shared/conduct/precedent.md) | Log self-observed failures to `state/precedent-log.md`; consult before risky steps |

---

## Architecture

Auto-generated from `plugin.json` + `hooks.json` + skill/agent frontmatter — can't go stale.

<p align="center">
  <img src="docs/assets/highlevel.svg"
       alt="Weaver high-level: 9 plugins coordinating through the enchanted-mcp event bus"
       width="100%" style="max-width: 900px;">
</p>

<details>
<summary>View all four diagrams (regenerated from plugin.json &amp; hooks.json)</summary>

- [High level](docs/assets/highlevel.svg) — plugins + hook phases
- [Hook detail](docs/assets/hooks.svg) — every script + tool matcher + timeout
- [Data flow](docs/assets/dataflow.svg) — per-plugin metrics → mcp-event-bus
- [Session lifecycle](docs/assets/lifecycle.svg) — SessionStart → PreToolUse → PostToolUse → PreCompact

Regenerate:

```bash
python docs/architecture/generate.py
npx -y -p @mermaid-js/mermaid-cli mmdc -i docs/architecture/highlevel.mmd \
  -o docs/assets/highlevel.svg -c docs/assets/mermaid.config.json -b "#0d1117" -w 1400
# ...repeat for hooks / dataflow / lifecycle
```

</details>

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). TL;DR: zero pip installs, honest scoring, per-sub-plugin structure identical, tests pass, Assembler boundary respected (Weaver reads CI; Weaver does not trigger builds).

---

## License

MIT. See [LICENSE.txt](LICENSE.txt).
