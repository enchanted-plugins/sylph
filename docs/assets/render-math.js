// Render LaTeX equations to self-contained SVGs using MathJax.
// GitHub mobile renders images but not $$...$$ — every equation in
// docs/science/README.md is pre-rendered here and referenced as <img>.
//
// Usage:
//   npm install --prefix . mathjax-full   # once
//   node render-math.js

const fs = require("fs");
const path = require("path");

const MJ_PATH = path.join(__dirname, "node_modules", "mathjax-full");
require(path.join(MJ_PATH, "js", "util", "asyncLoad", "node.js"));

const { mathjax } = require(path.join(MJ_PATH, "js", "mathjax.js"));
const { TeX } = require(path.join(MJ_PATH, "js", "input", "tex.js"));
const { SVG } = require(path.join(MJ_PATH, "js", "output", "svg.js"));
const { liteAdaptor } = require(path.join(MJ_PATH, "js", "adaptors", "liteAdaptor.js"));
const { RegisterHTMLHandler } = require(path.join(MJ_PATH, "js", "handlers", "html.js"));
const { AllPackages } = require(path.join(MJ_PATH, "js", "input", "tex", "AllPackages.js"));

const adaptor = liteAdaptor();
RegisterHTMLHandler(adaptor);

const tex = new TeX({ packages: AllPackages });
const svg = new SVG({ fontCache: "none" });
const html = mathjax.document("", { InputJax: tex, OutputJax: svg });

const FG = "#e6edf3";
const OUT = path.join(__dirname, "math");
fs.mkdirSync(OUT, { recursive: true });

// Labels follow ecosystem.md (W1=Myers-Diff Conventional Classifier,
// W2=Jaccard-Cosine Boundary, W3=Workflow Pattern Classifier,
// W4=Path-History Reviewer Routing, W5=Gauss Learning).
// W3 is a decision tree (no closed-form formula) and is omitted.
const EQUATIONS = [
  ["w1-valid",
   String.raw`\mathrm{valid}(m) \iff \begin{cases} \mathrm{type}(m) \in \mathcal{T} \\ |\mathrm{subject}(m)| \leq 72 \\ \mathrm{body\_line\_len}(m) \leq 72 \\ \mathrm{breaking\_marker}(m) \Rightarrow \mathrm{api\_path}(m) \end{cases}`],
  ["w2-distance",
   String.raw`d(a, b) = 0.4\,(1 - J(F_a, F_b)) + 0.4\,(1 - \cos(\vec{e}_a, \vec{e}_b)) + 0.2\,\tanh\!\left(\tfrac{t_b - t_a}{300}\right)`],
  ["w2-boundary",
   String.raw`\mathrm{boundary}(a, b) \iff d(a, b) > 0.55`],
  ["w4-score",
   String.raw`\mathrm{score}(r, f) = w_{\mathrm{rec}}(t, T_{1/2}=90\text{d}) \cdot \mathrm{depth}(r, f) + \mathbb{1}_{r \in \mathrm{CODEOWNERS}(f)} \cdot \beta`],
  ["w4-recency",
   String.raw`w_{\mathrm{rec}}(t) = \exp\!\left(-\ln 2 \cdot \dfrac{t_{\mathrm{now}} - t}{90\,\mathrm{d}}\right)`],
  ["w5-ema",
   String.raw`s_{\mathrm{new}} = \alpha \cdot s_{\mathrm{current}} + (1 - \alpha) \cdot s_{\mathrm{prior}} \qquad \alpha = 0.3`],
  ["w5-bootstrap",
   String.raw`\mathrm{confidence}(s) \iff \mathrm{sample\_count}(s) \geq 10`],
];

function render(name, source) {
  const node = html.convert(source, { display: true, em: 16, ex: 8, containerWidth: 1200 });
  let svgStr = adaptor.innerHTML(node);
  svgStr = svgStr.replace(/currentColor/g, FG);
  svgStr = `<?xml version="1.0" encoding="UTF-8"?>\n` + svgStr;
  fs.writeFileSync(path.join(OUT, `${name}.svg`), svgStr, "utf8");
  console.log(`  docs/assets/math/${name}.svg`);
}

console.log(`Rendering ${EQUATIONS.length} equations...`);
for (const [name, src] of EQUATIONS) {
  try { render(name, src); } catch (err) {
    console.error(`FAILED: ${name}\n  ${err.message}`);
    process.exitCode = 1;
  }
}
console.log("Done.");
