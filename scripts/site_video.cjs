// Grava o vídeo de demonstração da landing com o APP DE VERDADE (tempo real, sem cortes): envio do contrato →
// IA acha os campos → colar a mensagem do cliente → IA preenche → IA revisa → PDF pronto.
//
// Pré-requisitos: stack com a IA ligada (docker-compose.ai.yml) e o Edge instalado. Uso (de dentro de frontend/):
//   VIDEO_BASE=http://localhost:3210 node ../scripts/site_video.cjs
// Saída: scripts/.media-originals/video/demo-raw.webm (+ marcações de tempo em demo-steps.json).
// Depois: python ../scripts/site_video_encode.py (gera mp4/webm/poster em public/site e atualiza o manifesto).
// Custo de IA por gravação: ~US$ 0,003 (análise + preencher + revisar). Dados 100% fictícios.
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(require.resolve("playwright", { paths: [process.cwd()] }));

const BASE = process.env.VIDEO_BASE || "http://localhost:3210";
const OUT = path.resolve(__dirname, ".media-originals", "video");
const DOCX = path.resolve(__dirname, "..", "demo", "contrato_prestacao_servicos.docx");
const W = 1440;
const H = 900;

const PASTE =
  "Oi, Carolina! Tudo certo, pode fazer o contrato 😊\n" +
  "Meu nome completo é Marina Duarte Campos, CPF 529.982.247-25.\n" +
  "A contratada é a Estúdio Exemplo Serviços Ltda., CNPJ 11.222.333/0001-81.\n" +
  "Serviço: consultoria em marketing digital, R$ 3.200,00 por mês, por 12 meses, começando em 10/11/2026.\n" +
  "Pode deixar a renovação automática. Assinamos em São Paulo, dia 03/11/2026.";

// cursor e legenda desenhados na própria página (o vídeo do navegador não mostra o mouse)
const OVERLAY = () => {
  const boot = () => {
    if (document.getElementById("__cursor")) return;
    const c = document.createElement("div");
    c.id = "__cursor";
    c.style.cssText =
      "position:fixed;left:0;top:0;width:22px;height:22px;margin:-3px 0 0 -3px;z-index:2147483647;pointer-events:none;transition:transform .05s linear;" +
      "background:url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><path d='M4 2l15 10-7 1 4 8-3 1-4-8-5 5z' fill='%23111' stroke='white' stroke-width='1.5'/></svg>\") no-repeat;";
    document.body.appendChild(c);
    const r = document.createElement("div");
    r.id = "__ripple";
    r.style.cssText = "position:fixed;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;background:rgba(99,102,241,.35);z-index:2147483646;pointer-events:none;opacity:0;transition:opacity .35s,transform .35s;transform:scale(.4)";
    document.body.appendChild(r);
    const cap = document.createElement("div");
    cap.id = "__caption";
    cap.style.cssText =
      "position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:2147483645;pointer-events:none;max-width:80%;" +
      "background:rgba(9,9,11,.88);color:#fff;font:600 19px/1.35 'Plus Jakarta Sans',system-ui,sans-serif;padding:12px 20px;border-radius:14px;" +
      "box-shadow:0 10px 30px rgba(0,0,0,.25);opacity:0;transition:opacity .3s";
    document.body.appendChild(cap);
    addEventListener("mousemove", (e) => (c.style.transform = `translate(${e.clientX}px,${e.clientY}px)`), true);
    addEventListener("mousedown", (e) => {
      r.style.left = e.clientX + "px";
      r.style.top = e.clientY + "px";
      r.style.opacity = "1";
      r.style.transform = "scale(1)";
      setTimeout(() => ((r.style.opacity = "0"), (r.style.transform = "scale(.4)")), 260);
    }, true);
  };
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", boot);
  else boot();
};

async function caption(page, text) {
  await page.evaluate((t) => {
    const el = document.getElementById("__caption");
    if (!el) return;
    el.style.opacity = t ? "1" : "0";
    if (t) el.textContent = t;
  }, text);
}

const pause = (page, ms) => page.waitForTimeout(ms);

let mouse = { x: W / 2, y: H / 2 };
let current = null; // página em gravação (para capturar a tela se algo falhar)
async function moveTo(page, locator) {
  const box = await locator.boundingBox();
  if (!box) return;
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y, { steps: Math.max(12, Math.round(Math.hypot(x - mouse.x, y - mouse.y) / 18)) });
  mouse = { x, y };
}
async function click(page, locator) {
  await locator.scrollIntoViewIfNeeded();
  await moveTo(page, locator);
  await pause(page, 250);
  await locator.click();
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ channel: "msedge" });

  // 1) conta nova, fora do vídeo
  const setup = await browser.newContext({ baseURL: BASE });
  const email = `video-${Date.now()}@docfeito.com.br`;
  const reg = await setup.request.post("/api/v1/auth/register", {
    data: { name: "Carolina Mendes", email, password: "video-demo-123", workspace_name: "Mendes Assessoria" },
  });
  if (!reg.ok()) throw new Error(`cadastro falhou: ${reg.status()} ${await reg.text()}`);
  const state = await setup.storageState();
  await setup.close();

  // 2) gravação
  const ctx = await browser.newContext({ baseURL: BASE, viewport: { width: W, height: H }, storageState: state, recordVideo: { dir: OUT, size: { width: W, height: H } } });
  await ctx.addInitScript(OVERLAY);
  const page = await ctx.newPage();
  current = page;
  const t0 = Date.now();
  const steps = [];
  const mark = (name) => steps.push({ name, t: (Date.now() - t0) / 1000 });

  await page.goto("/dashboard");
  await page.getByTestId("home-new-model").waitFor();
  await page.mouse.move(mouse.x, mouse.y);
  mark("inicio");
  await pause(page, 600);
  await caption(page, "1. Envie o contrato que você já usa");
  await moveTo(page, page.getByTestId("home-new-model").getByRole("button", { name: /Escolher arquivo/ }));
  await pause(page, 900);
  await page.getByTestId("docx-input").setInputFiles({
    name: "Contrato de prestação de serviços.docx",
    mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    buffer: fs.readFileSync(DOCX),
  });
  mark("upload");
  await caption(page, "2. A IA lê o documento e encontra nome, CPF, valores e datas");
  await page.waitForURL(/\/generators\/.+\/edit/, { timeout: 90_000 });
  await page.getByTestId("doc-page").waitFor();
  mark("editor");
  await pause(page, 1200);
  await click(page, page.getByRole("tab", { name: /Sugestões/ }));
  await caption(page, "Sugestões prontas: é só conferir");
  await pause(page, 2600);
  await caption(page, "3. Aceite as sugestões: o modelo está pronto");
  await click(page, page.getByTestId("accept-all"));
  mark("aceitou");
  await pause(page, 2600);

  const id = page.url().match(/generators\/([^/]+)/)[1];
  await caption(page, "");
  await page.goto(`/generators/${id}/use`);
  await page.getByTestId("ai-fill").waitFor();
  mark("preencher");
  await pause(page, 900);
  await caption(page, "4. Cole a mensagem do cliente…");
  await click(page, page.getByTestId("ai-fill").getByRole("button", { name: /Preencher com IA/ }));
  await pause(page, 500);
  const box = page.getByTestId("ai-fill-text");
  await moveTo(page, box);
  await box.click();
  await box.fill(PASTE);
  await pause(page, 1600);
  await caption(page, "…e a IA preenche o formulário (só com o que está no texto)");
  const fill = page.waitForResponse((r) => r.url().includes("/assist/fill"));
  await click(page, page.getByTestId("ai-fill-run"));
  await fill;
  mark("preencheu");
  await pause(page, 3200);
  await page.mouse.wheel(0, 420);
  await pause(page, 1500);

  await caption(page, "5. Antes de gerar, a IA revisa datas, nomes e valores");
  const review = page.waitForResponse((r) => r.url().includes("/assist/review"));
  await click(page, page.getByTestId("ai-review"));
  await review;
  await page.getByTestId("ai-review-result").waitFor();
  mark("revisou");
  await pause(page, 3800);
  await page.keyboard.press("Escape");
  await pause(page, 600);

  await caption(page, "6. Documento pronto, em Word ou PDF");
  await click(page, page.getByTestId("generate-pdf"));
  mark("gerar");
  await page.getByRole("button", { name: /Baixar/ }).first().waitFor({ timeout: 90_000 });
  mark("pronto");
  await moveTo(page, page.getByRole("button", { name: /Baixar/ }).first());
  await pause(page, 3000);
  mark("fim");

  const video = page.video();
  await ctx.close();
  const raw = path.join(OUT, "demo-raw.webm");
  fs.copyFileSync(await video.path(), raw);
  fs.writeFileSync(path.join(OUT, "demo-steps.json"), JSON.stringify({ email, steps }, null, 2));
  console.log(JSON.stringify(steps));
  console.log("vídeo:", raw);
  await browser.close();
})().catch(async (e) => {
  console.error(e);
  if (current) await current.screenshot({ path: path.join(OUT, "erro.png") }).catch(() => {});
  process.exit(1);
});
