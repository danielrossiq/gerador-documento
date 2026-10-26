import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { DOCX } from "./helpers";

// Teste grátis (D38), casos além do caminho feliz do trial.spec.ts: guardar entrando numa conta que já existe,
// o fluxo inteiro no celular, link de teste vencido/inválido e erro do servidor mostrado na landing.
// Cada execução faz 3 testes pelo mesmo IP: rode o stack com limites altos, senão o 4º teste da hora (somando o
// trial.spec.ts) recebe "Você já fez muitos testes por agora":
//   TRIAL_LIMIT_IP_HOUR=1000 TRIAL_LIMIT_IP_DAY=1000 TRIAL_LIMIT_NET_DAY=1000 scripts/stack_local.sh restart-api
const FIX = path.resolve(__dirname, "fixtures");
const PASSWORD = "senha-forte-123";

async function trialOn(page: Page) {
  const cfg = (await (await page.request.get("/api/v1/public/trials/config")).json()) as { enabled: boolean; turnstile_site_key: string | null };
  test.skip(!cfg.enabled, "teste grátis desligado neste stack");
  test.skip(!!cfg.turnstile_site_key, "Turnstile ligado: este arquivo roda sem o desafio");
}

async function runTrial(page: Page) {
  await page.goto("/#teste");
  const trial = page.getByTestId("trial");
  await trial.getByTestId("trial-file").setInputFiles(DOCX);
  await expect(trial.getByTestId("trial-count")).toContainText("campos encontrados", { timeout: 60_000 });
  const href = (await trial.getByTestId("trial-save").getAttribute("href")) ?? "";
  expect(href).toMatch(/^\/register\?trial=[A-Za-z0-9_-]{40,64}$/);
  return { trial, token: href.split("trial=")[1] };
}

async function fillRegister(page: Page, email: string) {
  await page.locator('input[autocomplete="name"]').fill("Visitante QA");
  await page.getByLabel(/^E-mail/).fill(email);
  await page.getByLabel(/^Senha/).first().fill(PASSWORD);
  await page.getByLabel(/^Confirmar senha/).fill(PASSWORD);
  await page.getByRole("button", { name: "Criar conta" }).click();
}

test.describe("teste grátis — casos do QA", () => {
  test("quem já tem conta entra pelo link do cadastro e o documento vira modelo", async ({ page, browser }) => {
    await trialOn(page);
    // conta existente, criada em outro contexto (sem sessão nesta página)
    const email = `qa-login-${Date.now()}@exemplo.test`;
    const other = await browser.newContext();
    const r = await other.request.post("/api/v1/auth/register", { data: { name: "Conta QA", email, password: PASSWORD } });
    expect(r.status()).toBe(201);
    await other.close();

    const { trial, token } = await runTrial(page);
    await trial.getByTestId("trial-save").click();
    await page.waitForURL("**/register?trial=*");
    await page.getByRole("link", { name: /Entrar/ }).click();
    await page.waitForURL(`**/login?trial=${token}`);
    await page.getByLabel(/^E-mail/).fill(email);
    await page.getByLabel(/^Senha/).fill(PASSWORD);
    await page.getByRole("button", { name: "Entrar" }).click();
    await page.waitForURL(/\/generators\/[0-9a-f-]{36}\/edit/, { timeout: 30_000 });
    const gid = page.url().match(/generators\/([0-9a-f-]{36})/)![1];
    const sug = (await (await page.request.get(`/api/v1/generators/${gid}/suggestions`)).json()) as { items: unknown[] };
    expect(sug.items.length).toBeGreaterThan(0);
    expect((await page.request.get(`/api/v1/public/trials/${token}`)).status()).toBe(404);
  });

  test("no celular: envia, vê os campos, cria a conta e cai na etapa Campos", async ({ browser }) => {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, locale: "pt-BR", isMobile: true, hasTouch: true });
    const page = await ctx.newPage();
    await trialOn(page);
    const { trial } = await runTrial(page);
    await expect(trial.getByTestId("trial-fields")).toContainText("CPF");
    const save = trial.getByTestId("trial-save");
    await save.scrollIntoViewIfNeeded();
    await expect(save).toBeInViewport();
    const box = await save.boundingBox();
    expect(box!.height).toBeGreaterThanOrEqual(40); // alvo de toque confortável
    await save.tap();
    await page.waitForURL("**/register?trial=*");
    await fillRegister(page, `qa-cel-${Date.now()}@exemplo.test`);
    await page.waitForURL(/\/generators\/[0-9a-f-]{36}\/edit/, { timeout: 30_000 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    await ctx.close();
  });

  test("link de teste vencido ou inválido não trava o cadastro", async ({ page }) => {
    await trialOn(page);
    const bogus = "A".repeat(43); // formato válido, mas não existe (vencido e apagado)
    await page.goto(`/register?trial=${bogus}`);
    await expect(page.getByText("Seu documento está guardado por 1 hora")).toBeVisible();
    await fillRegister(page, `qa-vencido-${Date.now()}@exemplo.test`);
    await page.waitForURL("**/dashboard", { timeout: 30_000 });
    // lixo na URL nem chega à API
    await page.goto("/register?trial=../../api/v1/auth/logout");
    await expect(page.getByText("Seu documento está guardado por 1 hora")).toHaveCount(0);
  });

  test("arquivo que o servidor recusa mostra a mensagem na landing", async ({ page }) => {
    await trialOn(page);
    await page.goto("/#teste");
    const trial = page.getByTestId("trial");
    // foto com nome de .docx: passa na checagem do navegador (extensão/tamanho) e o servidor recusa pelo conteúdo
    await trial.getByTestId("trial-file").setInputFiles({
      name: "contrato.docx",
      mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      buffer: fs.readFileSync(path.join(FIX, "conta_de_luz_ficticia.jpg")),
    });
    await expect(trial.getByRole("alert")).toContainText(/Word \(\.docx\)|PDF digitado/, { timeout: 30_000 });
    await expect(trial.getByTestId("trial-count")).toHaveCount(0);
  });
});
