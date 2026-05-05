# Frequently asked questions

Quick answers to questions that don't yet have their own doc. For anything deeper, follow the links — the full answer usually lives in a neighboring file.

## What's the difference between Sylph and the other siblings?

Sylph answers *"how does this ship?"* — it classifies your git workflow, drafts commits, opens PRs, routes reviewers, reads CI, gates destructive ops, and learns per-developer preferences. Sibling plugins answer different questions: Wixie engineers prompts, Emu tracks token spend, Crow watches change trust, Hydra scans for security surface. All are independent installs. See [docs/ecosystem.md](ecosystem.md) for the full map.

## Do I need the other siblings to use Sylph?

No. Sylph is self-contained — install `full@sylph` and every command works standalone. If Crow is present, Sylph's `sylph-gate` inherits Crow's trust signal for reviewer availability; without Crow, it falls back to recency + CODEOWNERS. Neither is a hard dependency.

## How do I report a bug vs. ask a question vs. disclose a security issue?

- **Security vulnerability** — private advisory, never a public issue. See [SECURITY.md](../SECURITY.md).
- **Reproducible bug** — a bug report issue with repro steps + exact versions.
- **Usage question or half-formed idea** — [Discussions](https://github.com/enchanter-ai/sylph/discussions).

The [SUPPORT.md](../SUPPORT.md) page has the exact links for each.

## Is Sylph an official Anthropic product?

No. Sylph is an independent open-source plugin for [Claude Code](https://github.com/anthropics/claude-code) (Anthropic's CLI). It's published by [enchanter-ai](https://github.com/enchanter-ai) under the MIT license and is not affiliated with, endorsed by, or supported by Anthropic.

## Does Sylph work with all 10 git hosts equally?

Not today. **Live-tested:** GitHub — a real branch created, PR opened via the urllib adapter path, round-tripped, and closed. **Contract-tested:** all 10 hosts via `tests/pr-lifecycle/test-all-hosts-contract.sh`, which asserts every adapter instantiates cleanly, reports `is_authenticated` honestly, and refuses to fabricate a PR when credentials are absent. When you drop a GitLab / Bitbucket / Azure / Gitea token in, you're using the same `_rest.api_request` call path that shipped through GitHub's real API — if something breaks, it's in the per-host JSON shape, not the flow. The README is explicit about this; we don't pretend otherwise.

## Does Sylph trigger CI builds?

No — by design. Sylph's `ci-reader` **reads** check runs from 10 CI systems; it does not start builds. Sylph is a git-workflow plugin; CI execution belongs to your existing CI pipelines (push-triggered workflows, etc.). The read-only stance is documented in [CLAUDE.md](../CLAUDE.md) and called out in every CONTRIBUTING PR review.
