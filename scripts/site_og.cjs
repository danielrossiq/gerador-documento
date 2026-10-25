// Imagem de compartilhamento (Open Graph 1200×630) do DocFeito: logo, assinatura e uma tela real do app.
// Uso (de dentro de frontend/): node ../scripts/site_og.cjs  → frontend/public/site/og-1200.png (o .webp sai pelo Pillow)
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(require.resolve("playwright", { paths: [process.cwd()] }));

const ROOT = path.resolve(__dirname, "..");
const b64 = (p) => fs.readFileSync(p).toString("base64");
const logo = fs.readFileSync(path.join(ROOT, "frontend", "public", "brand", "docfeito-logo-negativo.svg"), "utf-8").replace(/ width="[\d.]+" height="[\d.]+"/, "");
const shot = b64(path.join(__dirname, ".media-originals", "shots", "preencher.png"));
const jakarta = b64(path.join(__dirname, ".media-originals", "brand", "PlusJakartaSans-latin.woff2"));

const html = `<!doctype html><meta charset="utf-8"><style>
@font-face{font-family:J;src:url(data:font/woff2;base64,${jakarta}) format("woff2");font-weight:200 800}
html,body{margin:0}body{width:1200px;height:630px;overflow:hidden;background:#0e1a2b;font-family:J;color:#fff;position:relative}
.glow{position:absolute;inset:0;background:radial-gradient(700px 380px at 95% -10%,rgb(18 184 134/.35),transparent 60%),radial-gradient(500px 300px at -10% 110%,rgb(255 212 59/.12),transparent 60%)}
.left{position:absolute;left:72px;top:72px;width:560px}
.logo{width:300px}
h1{font-weight:800;font-size:66px;line-height:1.04;letter-spacing:-.03em;margin:46px 0 0}
.m{background:linear-gradient(transparent 14%,#ffd43b 14%,#ffd43b 90%,transparent 90%);color:#0e1a2b;padding:0 .08em;-webkit-box-decoration-break:clone;box-decoration-break:clone}
p{font-size:25px;line-height:1.4;color:#c9d3e0;margin:26px 0 0;font-weight:600}
.shot{position:absolute;left:680px;top:110px;width:640px;border-radius:18px;box-shadow:0 30px 80px rgb(0 0 0/.5);border:1px solid rgb(255 255 255/.12)}
</style><div class="glow"></div><div class="left"><div class="logo">${logo}</div>
<h1>Documento feito. <span class="m">Sem copiar e colar.</span></h1>
<p>Seus contratos, procurações e recibos viram formulários. Gere 1 ou 1.000 em segundos.</p></div>
<img class="shot" src="data:image/png;base64,${shot}">`;

(async () => {
  const browser = await chromium.launch({ channel: "msedge" });
  const page = await browser.newPage({ viewport: { width: 1200, height: 630 } });
  await page.setContent(html, { waitUntil: "load" });
  await page.evaluate(() => document.fonts.ready);
  const out = path.join(ROOT, "frontend", "public", "site", "og-1200.png");
  await page.screenshot({ path: out });
  await browser.close();
  console.log(out);
})();
