// Capturas REAIS do app para as imagens da landing (scripts/site_compose.py). Edge headless, 2x.
// Uso: node scripts/site_shots.cjs  (variáveis: SHOTS_BASE, SHOTS_EMAIL, SHOTS_PASSWORD, SHOTS_CONTRACT, SHOTS_RECEIPT, SHOTS_KIT)
const path = require("node:path");
const fs = require("node:fs");
const { chromium } = require(path.join(__dirname, "..", "frontend", "node_modules", "@playwright/test"));

const BASE = process.env.SHOTS_BASE || "http://localhost:3210";
const OUT = path.join(__dirname, ".media-originals", "shots");
const EMAIL = process.env.SHOTS_EMAIL || "demo@docfeito.com.br";
const PASSWORD = process.env.SHOTS_PASSWORD || "demo12345"; // conta de demonstração do seed (dados fictícios)
const CONTRACT = process.env.SHOTS_CONTRACT;
const RECEIPT = process.env.SHOTS_RECEIPT;
const KIT = process.env.SHOTS_KIT;

const ROWS = [
  ["Mariana Costa Ribeiro", "529.982.247-25", "Consultoria em desenvolvimento de software", "4.500,00", "01/11/2026"],
  ["Rafael Nogueira Lima", "111.444.777-35", "Suporte técnico mensal", "1.850,00", "05/11/2026"],
  ["Beatriz Almeida Santos", "390.533.447-05", "Treinamento de equipes", "3.200,00", "10/11/2026"],
  ["Lucas Ferreira Prado", "714.602.380-01", "Suporte técnico mensal", "1.850,00", "12/11/2026"],
  ["Camila Duarte Moreira", "853.513.468-93", "Consultoria em desenvolvimento de software", "6.900,00", "15/11/2026"],
  ["Thiago Martins Barros", "275.484.389-23", "Treinamento de equipes", "2.750,00", "20/11/2026"],
];

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ channel: "msedge" });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, locale: "pt-BR" });
  const page = await ctx.newPage();
  await page.goto(`${BASE}/login`);
  await page.getByLabel(/^E-mail/).fill(EMAIL);
  await page.getByLabel(/^Senha/).fill(PASSWORD);
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.waitForURL("**/dashboard");

  const shot = async (name, url, size, prep) => {
    await page.setViewportSize(size);
    await page.goto(`${BASE}${url}`, { waitUntil: "networkidle" });
    if (prep) {
      await prep();
      await page.waitForTimeout(6500); // o aviso "campos preenchidos com exemplo" some sozinho; não entra na foto
    }
    await page.waitForTimeout(900);
    await page.screenshot({ path: path.join(OUT, name) });
    console.log("ok", name);
  };

  if (CONTRACT) {
    await shot("editor.png", `/generators/${CONTRACT}/edit`, { width: 1440, height: 900 });
    // lote: o rascunho da planilha fica no navegador (mesma chave que a tela usa)
    await page.evaluate(({ id, rows }) => {
      const names = ["nome_do_contratante", "cpf_do_contratante", "tipo_de_servico", "valor_mensal", "data_de_inicio"];
      const data = rows.map((r, i) => ({ id: `r${i}`, v: Object.fromEntries(names.map((n, j) => [n, r[j]])) }));
      localStorage.setItem(`minuta:batch:${id}`, JSON.stringify(data));
    }, { id: CONTRACT, rows: ROWS });
    await shot("lote.png", `/generators/${CONTRACT}/batch`, { width: 1600, height: 900 });
  }
  if (RECEIPT) {
    await shot("preencher.png", `/generators/${RECEIPT}/use`, { width: 1180, height: 820 }, async () => {
      const fill = page.getByRole("button", { name: /dados de exemplo/i });
      if (await fill.count()) await fill.first().click();
    });
  }
  if (KIT) {
    await shot("kit.png", `/kits/${KIT}/use`, { width: 1440, height: 900 }, async () => {
      const fill = page.getByRole("button", { name: /dados de exemplo/i });
      if (await fill.count()) await fill.first().click();
    });
  }
  await browser.close();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
