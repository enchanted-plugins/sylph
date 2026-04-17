# capability-memory

**The provider "memory". Encodes how each of the 9 git hosts actually behaves.**

Hybrid update strategy: hardcoded baseline ships with the plugin, nightly CI refresh opens PRs against the registry file, runtime probe handles GitLab self-managed version drift only (one probe per session, cached 24h in `state/session-cache/`).

Schema fields: `id`, `display_name`, `api_base`, `auth_modes`, `rate_limits`, `webhook_signing`, `merge_strategies`, `has_merge_queue`, `has_draft_pr`, `codeowners_flavor`, `release_asset_support`, `markdown_flavor`, `known_quirks`, `support_level`.

Support levels: `first-class` (Tier-1), `best-effort` (Azure DevOps, Gitea/Forgejo/Codeberg), `read-only` (CodeCommit, SourceHut), `out-of-scope`. SourceHut's mailing-list PR workflow is the abstraction's edge case — capability schema is validated against a filled SourceHut example at build time.

## Install

Part of the [Weaver](../..) bundle:

```
/plugin marketplace add enchanted-plugins/weaver
/plugin install full@weaver
```

Standalone: `/plugin install capability-memory@weaver`.

## Components

| Type | Name | Role |
|------|------|------|
| Hook | SessionStart | Load registry, probe GitLab self-managed version |
| Script | capability_probe.py | Runtime version probe (stdlib + urllib) |
| State | capability-registry.json | The authoritative registry |

## Cross-plugin

Consumed by every plugin via direct state read (not event bus — registry is too cold for per-event transport).

Full architecture: [../../docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md#layer-4-provider-capability-registry--the-memory).
