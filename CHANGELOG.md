# Changelog

All notable changes to `weaver` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Tier-1 governance docs: `SECURITY.md`, `SUPPORT.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`.
- `.github/` scaffold: issue templates, PR template, CODEOWNERS, dependabot config.
- Tier-2 docs: `docs/getting-started.md`, `docs/installation.md`, `docs/troubleshooting.md`, `docs/glossary.md`, `docs/adr/README.md`.

## [0.0.1] — initial public release

The current shipped release. See [README.md](README.md) for the complete feature surface.

### Highlights
- 8 plugins covering the git-workflow lifecycle: capability-memory, weaver-gate, boundary-segmenter, weaver-learning, and sibling sub-plugins.
- 5 named engines (W1 Myers Diff, W2 Jaccard-Cosine, W3 Workflow Classifier, W4 Path-History, W5 Gauss Learning) — formal derivations in [docs/science/README.md](docs/science/README.md).
- 15 slash commands across the workflow lifecycle.
- 10 git hosts supported (GitHub, GitLab, Bitbucket, Gitea, Forgejo, and others).
- 10 CI systems recognized for read-only status reporting.
- Destructive-op decision gate (weaver-gate) modeled after the Hornet pattern.
- Boundary-segmenter: task-boundary clustering on post-tool events.
- Per-developer learning via W5 Gauss EMA — preferences persist across compaction.
- 28/28 tests passing. Zero runtime dependencies (bash + jq + Python stdlib).

[Unreleased]: https://github.com/enchanted-plugins/weaver/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/enchanted-plugins/weaver/releases/tag/v0.0.1
