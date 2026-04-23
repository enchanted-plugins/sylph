# Sylph — Agent Contract

Audience: Claude. Sylph owns the git-workflow layer of AI-assisted development. Observes Claude Code sessions, segments work into logical tasks, auto-branches, auto-commits per cohesive chunk, and auto-opens draft PRs with session context. Destructive ops always route through a Crow-style decision-gate.

## Lifecycle

Sylph is hook-driven, not skill-invoked. Auto-orchestration is the product's reason to exist.

| Event | Plugin | Role |
|-------|--------|------|
| `SessionStart` | capability-memory | Load provider registry, probe GitLab self-managed version |
| `PostToolUse(Edit\|Write)` | boundary-segmenter | W2 clusters edit events into task boundaries |
| On boundary | branch-workflow + commit-intelligence | W3 picks branch strategy, W1 drafts Conventional Commits message |
| On cluster close | pr-lifecycle | W4 opens draft PR, routes reviewers, subscribes to CI status |
| `PreToolUse(Bash)` | sylph-gate | Destructive-op decision-gate (force-push, rebase, reset, clean) |
| On CI status change | ci-reader | Reads status from 10 CI systems (see [plugins/ci-reader/state/ci-registry.json](plugins/ci-reader/state/ci-registry.json)), gates merge-queue entry |
| `PreCompact` | sylph-learning | W5 checkpoints developer preferences + cluster state |

## Named engines (brand standard)

| ID | Name | Plugin | Algorithm |
|----|------|--------|-----------|
| W1 | Myers-Diff Conventional Classifier | commit-intelligence | Diff summarization + rule-based classifier + LLM re-rank |
| W2 | Jaccard-Cosine Boundary Segmentation | boundary-segmenter | Online agglomerative clustering, multi-modal distance. **Defining engine** |
| W3 | Workflow-Pattern Classifier | branch-workflow | Weighted decision tree over repo feature vector |
| W4 | Blame-Weighted Reviewer Ranker | pr-lifecycle | Blame score × recency decay × path depth × CODEOWNERS boost × availability filter; top-3 cap |
| W5 | Gauss Learning (Sylph) | sylph-learning | Weighted moving averages over preference signals, Emu-A4 persistence |

## Tier-1 vs Tier-2 hosts

| Host | Support Level | Notes |
|------|---------------|-------|
| GitHub (Cloud + Enterprise Server) | first-class | Check Runs API, Merge Queue, native CODEOWNERS |
| GitLab (SaaS + self-managed) | first-class | Merge Trains, version-probed at runtime |
| Bitbucket Cloud | first-class | Unsigned webhooks default — mitigated via shared-secret |
| Bitbucket Data Center | first-class | Different REST API from Cloud |
| Azure DevOps | best-effort | VSTS-era REST, scoped org/project/repo |
| Gitea / Forgejo / Codeberg | best-effort | GitHub-compatible subset |
| AWS CodeCommit | read-only | SigV4; no native PR UI |
| SourceHut | read-only | Mailing-list PRs — `git send-email`, no `pulls` abstraction |

Registry source of truth: **10 hosts** (github, gitlab, bitbucket-cloud, bitbucket-dc, azure-devops, gitea, forgejo, codeberg, codecommit, sourcehut) in [plugins/capability-memory/state/capability-registry.json](plugins/capability-memory/state/capability-registry.json) — gitea/forgejo/codeberg are collapsed above for presentation only. Schema v1.1 (24 fields/host) includes `signed_commit_verification`, `protected_branch_api`, `default_branch_convention`, `lfs_variant`, `release_api_path`, `webhook_event_taxonomy`, `pat_scopes_required`, `signed_tag_support`, `commit_status_api_shape`, `supports_draft_protected_branch_override`.

## CI/CD boundary

Sylph **reads** CI status across 10 systems (GitHub Actions, GitLab CI, CircleCI, Jenkins, Buildkite, Drone, Woodpecker, Tekton, ArgoCD, WixieCD — ArgoCD/WixieCD are read-only, not merge-queue gating; see [plugins/ci-reader/state/ci-registry.json](plugins/ci-reader/state/ci-registry.json)). Sylph is a git-workflow plugin; CI execution belongs to your existing CI pipelines (push-triggered workflows, etc.). Cross-plugin signals flow via the enchanted-mcp event bus:

### Phase 1 (shipped)

- **Sylph publishes**: `sylph.task.boundary.detected`, `sylph.commit.committed`, `sylph.pr.drafted`, `sylph.pr.ready`, `sylph.destructive.detected`, `sylph.ci.status.observed`
- **Sylph subscribes to**: `crow.session.continuity.node` (PR description context), `crow.reviewer.availability.changed` (W4 availability filter)

### Phase 2 aspirational (enchanted-mcp event bus not yet shipped)

The following subscriptions are reserved for cross-plugin event consumption when the enchanted-mcp event bus becomes available — Phase 1 Sylph runs standalone with no consumption of these events:

- `crow.change.classified` — Crow's code-change classification (reserved for PR risk scoring)
- `hydra.prepush.secret.detected` — Hydra secret-scanning findings (reserved for augmenting sylph-gate decisions)
- `pech.budget.threshold.crossed` — Pech token-budget alerts (reserved for session-pacing recommendations)

## Destructive-op contract

Every destructive op routes through sylph-gate. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#destructive-op-confirmation-contract) for the full table. Key rules:

- Force-push to protected branches: **never** bypassed.
- `git clean -fdx`: **never** bypassed (irrecoverable).
- Merge-queue `--admin` bypass: **never** without explicit `--admin-bypass` flag.
- All other destructive ops: `--yes-i-know` bypass for one invocation, always audited.

Audit log: `plugins/*/state/audit.jsonl` — append-only, Emu-A4 atomic pattern.

## Behavioral contracts

1. **IMPORTANT — Silent by default, loud when risky.** Auto-orchestration is invisible when it works. Decision-gates are blocking only for destructive ops. Nothing routine asks for permission.
2. **YOU MUST NOT write history rewrites without gate confirmation.** Even if the developer asks, route through `sylph-gate`. The developer's explicit confirmation is logged, not assumed.
3. **ESCALATE on SourceHut push operations.** SourceHut uses mailing-list PRs — if the developer's remote points to SourceHut, degrade to patch-email mode and surface the divergence.
4. **ESCALATE when the capability registry is stale.** If `state/capability-registry.json` is older than 30 days and the developer is on a Tier-1 host, nudge toward a nightly-refresh check.
5. **Ask, don't guess.** If `git status` is dirty at session-start or the branch naming doesn't match the detected workflow, ask before continuing. Never fabricate a task-boundary when none is certain.
6. **YOU MUST defer secret scanning to Hydra.** The `hydra.prepush.secret.detected` event is authoritative — Sylph blocks push when it fires, never second-guesses.
7. **YOU MUST NOT inflate clustering confidence.** W2 emits confidence per boundary; when confidence < 0.7, route to the Opus boundary-detector agent for judgment rather than acting autonomously.

## Brand standard compliance

- **Zero external runtime deps.** Hooks: bash + jq. Scripts: Python 3.8+ stdlib. `git-credential-manager` recommended; `gh auth` fast-path for GitHub. Tree-sitter gated behind `--deep-signals` flag.
- **Managed agents.** Opus for boundary judgment + PR description + conflict proposals. Sonnet for commit drafting + CODEOWNERS reasoning. Haiku for format validation + policy checks.
- **Gauss Accumulation (W5).** Per-developer preference persistence in `plugins/sylph-learning/state/learnings.json`, exported to `shared/learnings.json`.
- **Dark-themed PDF audit.** Ships from each plugin on final release.
- **Emu-style marketplace structure.** `plugins/<name>/{agents,commands,hooks,skills,state}` per sub-plugin.

## Anti-patterns

- **Owning CI execution.** Sylph is a reader, not a runner — do not add build-trigger code paths. CI execution belongs to your existing CI pipelines.
- **Auto-amending pushed commits.** W1's safe-amend detection must block this. Even if the Conventional Commits message is wrong, the fix is a follow-up commit, not `--amend`.
- **Silent history rewrite on late-boundary correction.** When W2 confidence is low (< 0.7), the boundary escalates to `/sylph:review-boundary` — an Opus agent judgment invoked via skill, never a silent `git rebase -i` or `git reset`. Low-confidence boundaries are surface for human review + learning, not silently rewritten.
- **Reviewer storms.** W4 caps auto-requested reviewers at 3. Larger pools rotate across subsequent PRs, not stacked on one.
- **GitHub-shaped assumptions in the abstraction layer.** The Provider Capability Schema must be filled for SourceHut (the hardest edge) before any host code ships — that's the test that proves the abstraction isn't GitHub-shaped underneath.

Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Crafted by Wixie at `wixie/prompts/sylph-architecture/` (σ=0.40, DEPLOY).
