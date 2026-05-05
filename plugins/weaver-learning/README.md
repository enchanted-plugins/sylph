# sylph-learning

**Developer preference persistence across sessions.**

Engine: **W5 — Gauss Learning (Sylph).**

Weighted moving averages over preference signals, persisted via Emu-A4 atomic serialization (tempfile + rename). Tracks:

- Preferred commit-message style (scope usage, body-length distribution)
- Preferred branch naming (slug-case vs kebab-case, prefix conventions)
- Typical PR turnaround timings (feeds W4 availability)
- W1 accept-vs-correct outcomes (feeds W1 priors on subsequent sessions)

After 6+ weeks, W1 and W3 adapt to the developer's style. Learnings export to `shared/learnings.json` — the Gauss Accumulation network that joins Wixie F6, Crow V6, and the wider ecosystem.

## Install

Part of the [Sylph](../..) bundle:

```
/plugin marketplace add enchanter-ai/sylph
/plugin install full@sylph
```

Standalone: `/plugin install sylph-learning@sylph`. Without W5, Sylph works but doesn't adapt — every session starts from the default priors.

## Components

| Type | Name | Role |
|------|------|------|
| Hook | PreCompact | Checkpoint learnings |
| Hook | SessionStart | Load priors |
| Script | atomic_json.py | Emu-A4 tempfile-rename pattern |
| State | learnings.json | The persisted preference vector |

## Cross-plugin

- **Consumes** `sylph.commit.committed`, `sylph.pr.merged`, developer-correction signals.
- **Exports** to `shared/learnings.json` — joined to the ecosystem Gauss Accumulation network.

Full architecture: [../../docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md#layer-10-plugin-runtime-hooks-safety--learning-w5).
