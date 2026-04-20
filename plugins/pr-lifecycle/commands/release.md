---
name: weaver:release
description: Cut a release — tag the current commit, compute the next semantic version from Conventional Commits since the last tag, generate a changelog entry, and hand off to semantic-release / release-please / changesets if the repo uses one of them. Weaver picks the tool automatically.
allowed-tools: Bash(git tag *), Bash(git push *), Bash(git log --format=*), Bash(git describe --tags *), Bash(semantic-release *), Bash(release-please *), Bash(changeset *), Read(package.json), Read(.release-please-manifest.json), Read(.changeset/config.json), Read(release.config.js)
---

# /weaver:release

Cut a release: tag + changelog + handoff to the repo's release tool.

## Usage

```
/weaver:release                          # detect tool + bump version from commits
/weaver:release --major                  # force major bump
/weaver:release --minor
/weaver:release --patch
/weaver:release --version 1.4.0          # explicit version (skips commit analysis)
/weaver:release --dry-run                # show planned bump + changelog, do nothing
/weaver:release --tool release-please    # force a specific tool
```

## Tool detection

Weaver picks the release tool from repo signals (first match wins):

| Signal | Tool chosen |
|---|---|
| `release.config.js` OR `release` key in package.json OR `.releaserc*` | **semantic-release** |
| `.release-please-manifest.json` OR `release-please-config.json` | **release-please** |
| `.changeset/config.json` | **changesets** |
| `.goreleaser.yml` | **goreleaser** |
| None of the above | **built-in** (Weaver tags + writes CHANGELOG.md itself) |

## Version bump (when Weaver computes it)

Reads `git log <last-tag>..HEAD --format='%s'` and runs the W1
Conventional Commits classifier on each subject:

- Any commit with `!` in the type OR a `BREAKING CHANGE:` footer → **major**
- Any `feat:` commit → **minor**
- Otherwise (`fix:`, `perf:`, `chore:`, etc.) → **patch**

Produces a changelog grouped by type:

```markdown
## 1.4.0 (2026-04-19)

### Features
- feat(auth): add OAuth PKCE flow (#142)
- feat(api): expose /v2/jobs endpoint (#144)

### Fixes
- fix: reject null session tokens (#145)
- fix(ui): offscreen click-through on modal (#146)

### Chores
- chore: bump deps (#147)
```

## Flow

```
1. Detect tool.
2. If external tool: shell out to it and stream output.
   semantic-release:  `npx semantic-release` (reads package.json + env)
   release-please:    `npx release-please release-pr --token=$GITHUB_TOKEN`
   changesets:        `npx changeset version && npx changeset publish`
   goreleaser:        `goreleaser release --clean`
3. If built-in:
   a. Read `git describe --tags --abbrev=0` for last tag (or v0.0.0 if none).
   b. Run classifier on every commit since that tag.
   c. Compute new version.
   d. Update CHANGELOG.md (prepend the new section).
   e. `git add CHANGELOG.md && /weaver:commit -m "chore(release): {version}"`.
   f. `git tag -s v{version} -m "release: {version}"` (signed if user.signingkey).
   g. weaver-gate inspects the tag push — `git push origin v{version}` is
      safe (new refs); `git push --delete` on existing tags is gated.
4. Publish weaver.release.tagged to state/metrics.jsonl.
```

## SBOM + provenance (opt-in)

With `--sbom` flag:

- Generates SPDX SBOM via `syft packages` if installed.
- Generates SLSA provenance via `cosign sign-blob` for the release artifact.
- Attaches both to the GitHub release via `gh release upload` (or the
  host-equivalent release asset endpoint when implemented).

Not enabled by default — these tools aren't stdlib.

## Safe defaults

- Refuses to tag a dirty working tree.
- Refuses to tag the wrong branch (uses `main` / `master` / `trunk` by
  default; `--from-branch` overrides).
- Never uses force-push for release branches.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Release tagged (or tool handoff succeeded) |
| 1 | Dirty tree / wrong branch |
| 2 | No commits since last tag |
| 3 | External tool failed (e.g., npm auth) |
