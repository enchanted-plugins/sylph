# Upgrading

Sylph follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Breaking changes only land on major version bumps (x.0.0).

## Between majors

Each major-to-major transition gets a dedicated section here with:

- A list of breaking changes.
- Specific migration steps users need to perform.
- A rollback path if the upgrade doesn't work.

Changes to the `HostAdapter` contract, the W3 workflow classifier's output labels, the `sylph-gate` destructive-op classification, or the ledger shapes emitted by W2/W5 **are** breaking. New host adapters, new CI systems, additional workflow classes, and pattern tuning are **not**.

## Current version

See [CHANGELOG.md](../CHANGELOG.md) for the current version and recent changes. As of this writing Sylph is on v0.0.1; no breaking-change migrations are documented yet. This page is a stub until the first tagged release and its eventual major bump.
