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

test("telas autenticadas críticas", async ({ page }) => {
  await login(page);
  await expect(page.getByRole("heading", { name: "Painel" })).toBeVisible();
  await expect(page.getByRole("table")).toBeVisible();
  await scan(page, "painel");

  const id = await demoGeneratorId(page);

  await page.goto(`/generators/${id}/edit`);
  await expect(page.getByTestId("doc-page")).toContainText("CONTRATO");
  await scan(page, "editor");
  await page.getByRole("button", { name: "Versões" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await scan(page, "diálogo de versões");
  await page.keyboard.press("Escape");

  await page.goto(`/generators/${id}/use`);
  await expect(page.getByTestId("generate-docx")).toBeVisible();
  await scan(page, "formulário individual");

  await page.goto(`/generators/${id}/batch`);
  await expect(page.getByTestId("batch-grid")).toBeVisible();
  await scan(page, "grade do lote");

  await page.goto("/history");
  await scan(page, "histórico");
});

test("navegação por teclado no menu de ações e no diálogo", async ({ page }) => {
  await login(page);
  const trigger = page.getByRole("button", { name: /^Ações de/ }).first();
  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("menuitem", { name: "Editar" })).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("menuitem", { name: "Editar" })).toBeHidden();
  await expect(trigger).toBeFocused(); // o foco volta ao gatilho
});
