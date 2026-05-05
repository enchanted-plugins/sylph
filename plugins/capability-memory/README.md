# capability-memory

**The provider "memory". Encodes how each of the 9 git hosts actually behaves.**

Hybrid update strategy: hardcoded baseline ships with the plugin, nightly CI refresh opens PRs against the registry file, runtime probe handles GitLab self-managed version drift only (one probe per session, cached 24h in `state/session-cache/`).

## Probe allowlist (security)

The SessionStart hook will ONLY emit an HTTPS request to a host on its allowlist. Default allow: `github.com`, `gitlab.com`, `bitbucket.org`, `codeberg.org`. For any other origin host, the probe is skipped and an advisory is emitted on stderr — this prevents a malicious repo from planting `git remote set-url origin https://attacker.example/...` to leak session presence + timing on every session start.

To enable probing for a self-managed GitLab/Gitea/Forgejo instance, append the host to `SYLPH_PROBE_ALLOWLIST` (space- or comma-separated) in your shell env or `.claude/settings.json` env block. Example:

```bash
export SYLPH_PROBE_ALLOWLIST="gitlab.example.com,git.internal"
```

Schema version: **1.1** (see `schema_changelog` in the registry for history).

Schema fields (23 per host):

- **v1.0 baseline (14):** `id`, `display_name`, `api_base`, `auth_modes`, `rate_limits`, `webhook_signing`, `merge_strategies`, `has_merge_queue`, `has_draft_pr`, `codeowners_flavor`, `release_asset_support`, `markdown_flavor`, `known_quirks`, `support_level`.
- **v1.1 additions (10):** `signed_commit_verification` (W1 amend-safety), `protected_branch_api` (sylph-gate force-push gating), `default_branch_convention` (W3 workflow classifier), `lfs_variant` (W2 `.gitattributes` cluster-distance), `release_api_path` (pr-lifecycle release flow), `webhook_event_taxonomy` (ci-reader + W4), `pat_scopes_required` (setup wizard), `signed_tag_support` (pr-lifecycle release signing), `commit_status_api_shape` (ci-reader gating), `supports_draft_protected_branch_override` (sylph-gate merge-queue bypass).

Support levels: `first-class` (Tier-1), `best-effort` (Azure DevOps, Gitea/Forgejo/Codeberg), `read-only` (CodeCommit, SourceHut), `out-of-scope`. SourceHut's mailing-list PR workflow is the abstraction's edge case — capability schema is validated against a filled SourceHut example at build time.

## Install

Part of the [Sylph](../..) bundle:

```
/plugin marketplace add enchanter-ai/sylph
/plugin install full@sylph
```

Standalone: `/plugin install capability-memory@sylph`.

## Components

| Type | Name | Role |
|------|------|------|
| Hook | SessionStart | Load registry, probe allowlisted GitLab self-managed version |
| Script | capability_probe.py | Runtime version probe (stdlib + urllib) |
| State | capability-registry.json | The authoritative registry |

## Cross-plugin

Consumed by every plugin via direct state read (not event bus — registry is too cold for per-event transport).

Full architecture: [../../docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md#layer-4-provider-capability-registry--the-memory).
