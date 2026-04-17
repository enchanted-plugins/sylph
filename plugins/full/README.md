# full

**Meta-plugin. Declares the other 8 plugins as dependencies so one install pulls in the whole Weaver pipeline.**

Same pattern as Flux's `full` and the other enchanted-plugins meta-plugins.

## Install

```
/plugin marketplace add enchanted-plugins/weaver
/plugin install full@weaver
```

That single command resolves dependencies and installs:

- `commit-intelligence` (W1)
- `boundary-segmenter` (W2 — defining engine)
- `branch-workflow` (W3)
- `pr-lifecycle` (W4)
- `weaver-gate` (destructive-op gate)
- `capability-memory` (provider registry)
- `ci-reader` (CI status, read-only)
- `weaver-learning` (W5)

Verify with `/plugin list` — expected: `full` plus the 8 above under the `weaver` marketplace.

## Why install `full` instead of cherry-picking

The plugins coordinate via the enchanted-mcp event bus. Cherry-picking is supported for isolated use (e.g. `commit-intelligence` alone for manual `/weaver commit` usage), but most cross-plugin flows depend on multiple plugins being present:

- Auto-orchestration needs `boundary-segmenter` + `branch-workflow` + `commit-intelligence` + `pr-lifecycle` at minimum.
- Safe destructive-op handling needs `weaver-gate` always.
- Host abstraction needs `capability-memory` always.

So `full` is the supported default. Cherry-pick only when you know which event flows you're opting out of.

Full architecture: [../../docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md).
