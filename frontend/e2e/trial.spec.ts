import { expect, test } from "@playwright/test";
import { DOCX } from "./helpers";

// Teste grátis na landing (D38): o visitante envia o documento dele, vê os campos e guarda o modelo na conta nova.
// Precisa da API com o teste ligado (padrão fora de produção) e sem Turnstile (TURNSTILE_SECRET_KEY vazio).
test.describe("teste grátis na landing", () => {
  test("envia o .docx, vê os campos marcados e guarda como modelo depois do cadastro", async ({ page }) => {
    const cspErrors: string[] = [];
    page.on("console", (m) => {
      if (m.type() === "error" && /Content Security Policy|CSP/i.test(m.text())) cspErrors.push(m.text());
    });
    const res = await page.goto("/#teste");
    expect(res?.headers()["content-security-policy"] ?? "").toMatch(/script-src 'self' 'nonce-[^']+' 'strict-dynamic'/);
    const trial = page.getByTestId("trial");
    await expect(trial).toBeVisible();
    await expect(trial).toContainText("apagado em 1 hora");

    await trial.getByTestId("trial-file").setInputFiles(DOCX);
    await expect(trial.getByTestId("trial-count")).toContainText("campos encontrados", { timeout: 60_000 });
    const fields = trial.getByTestId("trial-fields");
    await expect(fields).toContainText("CPF");
    await expect(trial.getByTestId("doc-preview").locator('mark[data-found="true"]').first()).toBeVisible();

    const save = trial.getByTestId("trial-save");
    const href = (await save.getAttribute("href")) ?? "";
    expect(href).toMatch(/^\/register\?trial=[A-Za-z0-9_-]{40,64}$/);
    await save.click();
    await page.waitForURL("**/register?trial=*");
    await expect(page.getByText("Seu documento está guardado por 1 hora")).toBeVisible();
    const email = `teste-${Date.now()}@exemplo.test`;
    await page.locator('input[autocomplete="name"]').fill("Visitante E2E");
    await page.getByLabel(/^E-mail/).fill(email);
    await page.getByLabel(/^Senha/).first().fill("senha-forte-123");
    await page.getByLabel(/^Confirmar senha/).fill("senha-forte-123");
    await page.getByRole("button", { name: "Criar conta" }).click();

    // vai direto para a etapa Campos do modelo novo, já com as sugestões do teste
    await page.waitForURL(/\/generators\/[0-9a-f-]{36}\/edit/, { timeout: 30_000 });
    const gid = page.url().match(/generators\/([0-9a-f-]{36})/)![1];
    const sug = await page.request.get(`/api/v1/generators/${gid}/suggestions`);
    const body = (await sug.json()) as { items: { suggested_type: string }[] };
    expect(body.items.some((i) => i.suggested_type === "cpf")).toBeTruthy();
    // o link do teste deixa de valer depois de guardado
    const token = href.split("trial=")[1];
    expect((await page.request.get(`/api/v1/public/trials/${token}`)).status()).toBe(404);
    expect(cspErrors).toEqual([]);
  });

  test("link de teste vencido no cadastro e no login explica o que fazer", async ({ page }) => {
    const gone = "x".repeat(43);
    await page.goto(`/register?trial=${gone}`);
    await expect(page.getByText("O documento do teste expirou ou já foi guardado")).toBeVisible();
    await page.goto(`/login?trial=${gone}`);
    await expect(page.getByText("O documento do teste expirou ou já foi guardado")).toBeVisible();
  });

  test("arquivo de tipo errado é recusado na hora, sem enviar", async ({ page }) => {
    await page.goto("/#teste");
    const trial = page.getByTestId("trial");
    await trial.getByTestId("trial-file").setInputFiles({ name: "nota.txt", mimeType: "text/plain", buffer: Buffer.from("oi") });
    await expect(trial.getByRole("alert")).toContainText(".docx");
  });

  test("no celular, o resultado cabe na tela sem rolagem horizontal", async ({ browser }) => {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, locale: "pt-BR" });
    const page = await ctx.newPage();
    await page.goto("/#teste");
    const trial = page.getByTestId("trial");
    await trial.getByTestId("trial-file").setInputFiles(DOCX);
    await expect(trial.getByTestId("trial-count")).toBeVisible({ timeout: 60_000 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    await ctx.close();
  });
});
