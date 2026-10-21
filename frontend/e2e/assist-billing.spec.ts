import { expect, test } from "@playwright/test";
import { demoGeneratorId, login, register } from "./helpers";

// Plano e uso (D34) e IA no preenchimento (D33).
// A IA só é testada quando o stack está com ela ligada (docker-compose.ai.yml); cada execução custa < US$ 0,01.

test("plano e uso: medidores, planos e cadastro vindo de um plano pago", async ({ page }) => {
  const email = `plano-${Date.now()}@e2e.test`;
  await page.goto("/register?plano=profissional&ciclo=mensal");
  await expect(page.getByText("Plano Profissional (mensal)")).toBeVisible();
  await page.locator('input[autocomplete="name"]').fill("Pessoa Plano");
  await page.getByLabel(/^E-mail/).fill(email);
  await page.getByLabel(/^Senha/).first().fill("senha-forte-123");
  await page.getByLabel(/^Confirmar senha/).fill("senha-forte-123");
  await page.getByRole("button", { name: "Criar conta" }).click();
  await page.waitForURL("**/assinatura?plano=profissional&ciclo=mensal");

  await expect(page.getByRole("heading", { name: "Plano e uso" })).toBeVisible();
  await expect(page.getByTestId("current-plan")).toContainText("Grátis");
  await expect(page.getByTestId("meter-docs")).toContainText("Documentos gerados");
  await expect(page.getByTestId("meter-ai")).toContainText("Usos de IA");
  await expect(page.getByTestId("plan-profissional")).toHaveClass(/ring-2/); // o plano escolhido na landing vem destacado
  await expect(page.getByTestId("cycle-mensal")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("plan-profissional")).toContainText("R$ 49,90");
  await page.getByTestId("cycle-anual").click();
  await expect(page.getByTestId("plan-profissional")).toContainText("R$ 39,90");
});

test("plano e uso fica no menu do usuário", async ({ page }) => {
  await register(page, `menu-${Date.now()}@e2e.test`);
  await page.getByRole("button", { name: /Conta de/ }).click();
  await page.getByRole("menuitem", { name: "Plano e uso" }).click();
  await page.waitForURL("**/assinatura");
});

test("preencher com IA a partir de um texto colado e revisar antes de gerar", async ({ page }) => {
  await login(page);
  const status = await (await page.request.get("/api/v1/assist/status")).json();
  test.skip(!status.enabled, "IA desligada neste stack");
  const id = await demoGeneratorId(page);
  await page.goto(`/generators/${id}/use`);
  try {
    await page.evaluate((k) => localStorage.removeItem(k), `minuta:form:${id}`);
  } catch {
    /* sem rascunho */
  }
  await page.reload();

  await page.getByTestId("ai-fill").getByRole("button", { name: /Preencher com IA/ }).click();
  await page.getByTestId("ai-fill-text").fill(
    "Bom dia! Seguem os dados para o contrato: sou Marina Duarte Campos, CPF 529.982.247-25, " +
      "moro na Rua das Acácias, 120, apto 31, Belo Horizonte/MG. O valor combinado foi R$ 3.200,00 por mês, " +
      "começando em 10/11/2026, por 12 meses.",
  );
  await page.getByTestId("ai-fill-run").click();
  await expect(page.getByText(/campos? preenchidos? pela IA/)).toBeVisible({ timeout: 45_000 });
  const filled = await page.locator('input[value*="Marina"]').count();
  expect(filled).toBeGreaterThan(0);

  await page.getByTestId("ai-review").click();
  await expect(page.getByTestId("ai-review-result")).toBeVisible({ timeout: 45_000 });
});
