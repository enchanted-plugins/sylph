# boundary-segmenter

**The defining engine. Detects task boundaries from the stream of file-edit events.**

Engine: **W2 — Jaccard-Cosine Boundary Segmentation.**

Each `PostToolUse(Edit|Write)` event produces a feature vector `{files, hornet_v1_embedding, timestamp}`. Distance between two events combines file-set Jaccard (α=0.4), Hornet-V1 semantic-diff cosine (β=0.4), and idle-time gap with `tanh((Δt)/τ=300s)` (γ=0.2). Events stream into an online agglomerative cluster; boundary fires when the next event's min cluster-distance exceeds θ=0.55. Multi-signal avoids Graphite's 2023 idle-timer-only failure mode.

Late-boundary correction surfaces as a skill invocation ("merge last N commits?") rather than silent history rewrite — destructive corrections always route through `weaver-gate`.

## Install

Part of the [Weaver](../..) bundle:

```
/plugin marketplace add enchanted-plugins/weaver
/plugin install full@weaver
```

Standalone: `/plugin install boundary-segmenter@weaver`. This is Weaver's core engine — without it, auto-orchestration doesn't exist.

## Components

| Type | Name | Role |
|------|------|------|
| Agent | boundary-detector (Opus) | Judgment calls when confidence in [θ-0.1, θ+0.1] |
| Hook | PostToolUse(Edit\|Write) | Feeds the segmenter |
| Hook | PreCompact | Checkpoints cluster state |
| Script | boundary_segment.py | Python stdlib online clustering |

## Cross-plugin

- **Requires** `hornet.change.classified` (Hornet V1 embedding is the substrate).
- **Publishes** `weaver.task.boundary.detected`.

Full architecture: [../../docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md#layer-6-task-boundary-segmentation-w2--defining-engine).
