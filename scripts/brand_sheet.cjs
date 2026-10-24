// Folha de contato: renderiza imagens (SVG/PNG/JPG) de scripts/.media-originals/brand lado a lado num PNG.
// Uso (de dentro de frontend/): node ../scripts/brand_sheet.cjs <prefixo> [saida.png]
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(require.resolve("playwright", { paths: [process.cwd()] }));

const DIR = path.resolve(__dirname, ".media-originals", "brand");
const prefix = process.argv[2] || "";
const out = process.argv[3] || path.join(DIR, `_sheet-${prefix || "all"}.png`);

(async () => {
  const files = fs.readdirSync(DIR).filter((f) => f.startsWith(prefix) && /\.(svg|png|jpe?g|webp)$/i.test(f) && !f.startsWith("_")).sort();
  const cells = files
    .map((f) => {
      const mime = f.endsWith(".svg") ? "image/svg+xml" : f.endsWith(".png") ? "image/png" : f.endsWith(".webp") ? "image/webp" : "image/jpeg";
      const data = fs.readFileSync(path.join(DIR, f)).toString("base64");
      return `<figure><div class="img"><img src="data:${mime};base64,${data}"></div><figcaption>${f}</figcaption></figure>`;
    })
    .join("");
  const html = `<!doctype html><meta charset="utf-8"><style>
    body{margin:0;padding:24px;background:#eceae4;font:13px system-ui;display:grid;grid-template-columns:repeat(${Math.min(4, files.length || 1)},300px);gap:20px}
    figure{margin:0;background:#fff;border-radius:12px;padding:12px;box-shadow:0 1px 3px #0002}
    .img{height:276px;display:grid;place-items:center}.img img{max-width:100%;max-height:100%}
    figcaption{margin-top:8px;color:#555;word-break:break-all}</style>${cells}`;
  const browser = await chromium.launch({ channel: "msedge" });
  const page = await browser.newPage({ viewport: { width: 1360, height: 400 } });
  await page.setContent(html);
  await page.screenshot({ path: out, fullPage: true });
  await browser.close();
  console.log(out, files.length, "imagens");
})();
