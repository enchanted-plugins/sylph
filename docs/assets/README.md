# docs/assets — rendered diagrams & equations

Pre-rendered SVGs so GitHub's mobile app (which renders neither
` ```mermaid ` blocks nor `$$...$$` math) shows them correctly. The
root `README.md` and `docs/science/README.md` reference the files
here as `<img>`.

## Files

| File | Source | Regenerate |
|------|--------|-----------|
| `highlevel.svg` | `../architecture/highlevel.mmd` | `npx @mermaid-js/mermaid-cli -i ../architecture/highlevel.mmd -o highlevel.svg -c mermaid.config.json -b "#0a1628" -w 1800 && node apply-blueprint.js highlevel.svg` |
| `hooks.svg` | `../architecture/hooks.mmd` | `npx @mermaid-js/mermaid-cli -i ../architecture/hooks.mmd -o hooks.svg -c mermaid.config.json -b "#0a1628" -w 1800 && node apply-blueprint.js hooks.svg` |
| `lifecycle.svg` | `../architecture/lifecycle.mmd` | `npx @mermaid-js/mermaid-cli -i ../architecture/lifecycle.mmd -o lifecycle.svg -c mermaid.config.json -b "#0a1628" -w 1800 && node apply-blueprint.js lifecycle.svg` |
| `dataflow.svg` | `../architecture/dataflow.mmd` | `npx @mermaid-js/mermaid-cli -i ../architecture/dataflow.mmd -o dataflow.svg -c mermaid.config.json -b "#0a1628" -w 1800 && node apply-blueprint.js dataflow.svg` |
| `pipeline.svg` | `pipeline.mmd` | `npx -y @mermaid-js/mermaid-cli -i pipeline.mmd -o pipeline.svg -c mermaid.config.json -p puppeteer.config.json -b "#0a1628" -w 1800 && node apply-blueprint.js pipeline.svg` |
| `state-flow.svg` | `state-flow.mmd` | `npx -y @mermaid-js/mermaid-cli -i state-flow.mmd -o state-flow.svg -c mermaid.config.json -p puppeteer.config.json -b "#0a1628" -w 1800 && node apply-blueprint.js state-flow.svg` |
| `math/*.svg` | `render-math.js` | `npm install --prefix . mathjax-full && node render-math.js` |

Run the commands from `docs/assets/` (paths are relative). The
toolchain (`node_modules/`, `package.json`, `package-lock.json`) is
gitignored; only the rendered SVGs and their sources are committed.

The `apply-blueprint.js` step overlays an engineering-blueprint grid
(navy `#0a1628` paper, `#1e3a5f` major lines / `#16304f` minor lines)
onto the rendered diagram so it reads as a CAD drawing rather than a
neutral dark card. Matches the look of the sibling repos (allay,
flux, hornet, reaper).

## Math assets

Formulas from `docs/science/README.md` (W1–W5) render to
`math/*.svg` via MathJax. Filenames match the `<img src>` references
in the science README (for example `w2-distance.svg`,
`w5-ema.svg`). Update `render-math.js` when adding a new formula and
re-run the render step.
