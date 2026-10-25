// Exporta os SVGs da marca (frontend/public/brand) em PNG com fundo transparente, nos tamanhos de uso.
// Renderiza o próprio vetor (não há fundo a remover). Uso (de dentro de frontend/): node ../scripts/brand_export.cjs
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(require.resolve("playwright", { paths: [process.cwd()] }));

const SRC = path.resolve(__dirname, "..", "frontend", "public", "brand");
const OUT = path.join(SRC, "png");

// [arquivo svg, larguras em px]
const JOBS = [
  ["docfeito-icone.svg", [16, 32, 48, 64, 128, 256, 512, 1024]],
  ["docfeito-icone-negativo.svg", [64, 256, 1024]],
  ["docfeito-icone-app.svg", [180, 192, 512, 1024]],
  ["docfeito-logo.svg", [480, 1024, 2048]],
  ["docfeito-logo-negativo.svg", [480, 1024, 2048]],
  ["docfeito-logo-mono-tinta.svg", [1024]],
  ["docfeito-logo-mono-branco.svg", [1024]],
  ["docfeito-logo-vertical.svg", [512, 1024]],
  ["docfeito-logo-vertical-negativo.svg", [512, 1024]],
];

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ channel: "msedge" });
  const page = await browser.newPage({ deviceScaleFactor: 1 });
  const made = [];
  for (const [file, widths] of JOBS) {
    const svg = fs.readFileSync(path.join(SRC, file), "utf-8");
    const m = svg.match(/viewBox="0 0 ([\d.]+) ([\d.]+)"/);
    const [vw, vh] = [Number(m[1]), Number(m[2])];
    for (const w of widths) {
      const h = Math.round((w * vh) / vw);
      await page.setViewportSize({ width: w, height: h });
      const sized = svg.replace(/width="[\d.]+" height="[\d.]+"/, `width="${w}" height="${h}"`);
      await page.setContent(`<!doctype html><style>html,body{margin:0;background:transparent}svg{display:block}</style>${sized}`);
      const name = `${file.replace(/\.svg$/, "")}-${w}.png`;
      await page.screenshot({ path: path.join(OUT, name), omitBackground: true, clip: { x: 0, y: 0, width: w, height: h } });
      made.push(name);
    }
  }
  await browser.close();
  console.log(`${made.length} PNGs em ${OUT}`);
})();
