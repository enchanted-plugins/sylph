# weaver-learning

**Developer preference persistence across sessions.**

Engine: **W5 — Gauss Learning (Weaver).**

Weighted moving averages over preference signals, persisted via Allay-A4 atomic serialization (tempfile + rename). Tracks:

- Preferred commit-message style (scope usage, body-length distribution)
- Preferred branch naming (slug-case vs kebab-case, prefix conventions)
- Typical PR turnaround timings (feeds W4 availability)
- W1 accept-vs-correct outcomes (feeds W1 priors on subsequent sessions)

After 6+ weeks, W1 and W3 adapt to the developer's style. Learnings export to `shared/learnings.json` — the Gauss Accumulation network that joins Flux F6, Hornet V6, and the wider ecosystem.

## Install

Part of the [Weaver](../..) bundle:

```
/plugin marketplace add enchanted-plugins/weaver
/plugin install full@weaver
```

Standalone: `/plugin install weaver-learning@weaver`. Without W5, Weaver works but doesn't adapt — every session starts from the default priors.

## Components

| Type | Name | Role |
|------|------|------|
| Hook | PreCompact | Checkpoint learnings |
| Hook | SessionStart | Load priors |
| Script | atomic_json.py | Allay-A4 tempfile-rename pattern |
| State | learnings.json | The persisted preference vector |

## Cross-plugin

- **Consumes** `weaver.commit.committed`, `weaver.pr.merged`, developer-correction signals.
- **Exports** to `shared/learnings.json` — joined to the ecosystem Gauss Accumulation network.

Full architecture: [../../docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md#layer-10-plugin-runtime-hooks-safety--learning-w5).
