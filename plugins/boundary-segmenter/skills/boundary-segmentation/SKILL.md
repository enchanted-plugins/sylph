---
name: boundary-segmentation
description: Explains how W2 Jaccard-Cosine Boundary Segmentation works, what events fire it, and how to interpret the cluster state in plugins/boundary-segmenter/state/boundary-clusters.json. Invoked when a developer asks "why did Sylph commit/branch here?" or "what's W2 doing?"
allowed-tools: Read
---

# boundary-segmentation

## What this is

Sylph's defining engine. Every `PostToolUse(Edit|Write|MultiEdit)` event
flows into an online agglomerative clusterer. When the next event's
distance to the active cluster exceeds threshold θ (default 0.55), a
task boundary fires — and that triggers the downstream plugins to branch,
commit, and eventually open a PR.

## The distance function

Three components, weighted:

```
d(event, cluster) = α · (1 − jaccard(files))         α = 0.4  (file overlap)
                  + β · (1 − cosine(tokens))         β = 0.4  (content overlap)
                  + γ · tanh(idle_gap / τ)           γ = 0.2, τ = 300s
```

Weights and threshold live in `shared/constants.sh` (`SYLPH_BOUNDARY_*`).
`sylph-learning` (W5) tunes them per-developer over time — the defaults
are what a fresh install starts with.

## How to read the state

`plugins/boundary-segmenter/state/boundary-clusters.json` contains:

- `threshold`, `uncertainty_band`, `cfg` (alpha/beta/gamma/tau)
- `active`: the currently-open cluster (opened_at, events[])
- `closed_clusters`: the last 20 finalized clusters

Each event in a cluster records `files`, `vector` (L2-normalized token
weights), `tool`, `timestamp`. The `vector` shows what tokens the
algorithm matched on — useful for debugging why two edits did or didn't
cluster together.

## When W2 upgrades to Crow V1

If Crow is installed and publishes `crow.change.classified` events on
the mcp-event-bus, Sylph will substitute Crow V1's semantic diff
embedding in place of the stdlib token vector. The API is the same; the
accuracy improves.

## When to invoke this skill

A developer asking:

- "Why did Sylph commit here?" → show the last closed cluster + distance.
- "Why didn't it commit yet?" → show the active cluster growing.
- "Can I tune this?" → point at `SYLPH_BOUNDARY_*` in `shared/constants.sh`
  and `sylph-learning/state/learnings.json` for per-dev overrides.
