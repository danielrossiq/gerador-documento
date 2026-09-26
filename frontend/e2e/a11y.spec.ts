import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { demoGeneratorId, login } from "./helpers";

// Verificação automática de acessibilidade (WCAG 2.x A/AA) nas telas críticas. Não substitui teste manual com leitor de tela.
async function scan(page: Page, name: string) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const summary = results.violations.map((v) => `${v.id} (${v.impact}): ${v.nodes.length} nó(s) — ${v.nodes[0]?.html.slice(0, 140)}`);
  expect(summary, `Violações de acessibilidade em ${name}`).toEqual([]);
}

test("login e cadastro", async ({ page }) => {
  await page.goto("/login");
  await scan(page, "login");
  await page.goto("/register");
  await scan(page, "cadastro");
});

test("telas autenticadas críticas (todas as etapas do gerador)", async ({ page }) => {
  await login(page);
  await expect(page.getByRole("heading", { name: "Geradores", level: 1 })).toBeVisible();
  await expect(page.getByTestId("generator-card").first()).toBeVisible();
  await scan(page, "painel");

  const id = await demoGeneratorId(page);

  await page.goto(`/generators/${id}/template`);
  await expect(page.getByTestId("current-file")).toBeVisible();
  await scan(page, "etapa Modelo");

  await page.goto(`/generators/${id}/edit`);
  await expect(page.getByTestId("doc-page")).toContainText("CONTRATO");
  await scan(page, "editor");
  await page.getByRole("button", { name: "Versões" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await scan(page, "diálogo de versões");
  await page.keyboard.press("Escape");

  await page.goto(`/generators/${id}/review`);
  await expect(page.getByTestId("review-checklist")).toBeVisible();
  await scan(page, "revisão");

  await page.goto(`/generators/${id}/use`);
  await expect(page.getByTestId("generate-docx")).toBeVisible();
  await scan(page, "formulário individual");

  await page.goto(`/generators/${id}/batch`);
  await expect(page.getByTestId("batch-grid")).toBeVisible();
  await scan(page, "grade do lote");

  await page.goto("/history");
  await scan(page, "histórico");
});

test("navegação por teclado: etapas, menu de ações e diálogo", async ({ page }) => {
  await login(page);
  const trigger = page.getByRole("button", { name: /^Mais ações de/ }).first();
  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("menuitem", { name: "Editar campos" })).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("menuitem", { name: "Editar campos" })).toBeHidden();
  await expect(trigger).toBeFocused(); // o foco volta ao gatilho

  // um link com cara de botão é UMA parada de Tab (antes: <a><button> = duas)
  const card = page.getByTestId("generator-card").first();
  const action = card.getByRole("link", { name: /Gerar documento|Criar campos|Enviar documento/ });
  await action.focus();
  await page.keyboard.press("Tab");
  await expect(action).not.toBeFocused();
  await expect(card.locator("button:focus, a:focus")).toHaveCount(1);

  // as etapas do gerador indicam a atual para leitores de tela
  const id = await demoGeneratorId(page);
  await page.goto(`/generators/${id}/review`);
  await expect(page.getByRole("navigation", { name: "Etapas do gerador" }).locator('[aria-current="step"]')).toContainText("Revisão");
});
