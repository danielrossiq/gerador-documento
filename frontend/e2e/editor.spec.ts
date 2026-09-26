import { expect, test } from "@playwright/test";
import { createUsableGenerator, register, waitSaved } from "./helpers";

// Editor (etapa Campos): pendências por campo, salvamento que não perde a última alteração ao trocar de campo,
// e revisão apontando o que falta com link direto para corrigir.
test("editor: avisa pendências e salva a alteração mesmo trocando de campo logo em seguida", async ({ page }) => {
  await register(page, `e2e-editor-${Date.now()}@exemplo.test`);
  // campos criados pela API não estão no texto (fora do documento) e a lista não tem opções
  const gid = await createUsableGenerator(page, "Editor E2E", [
    { label: "Nome", type: "text_short", required: true },
    { label: "Plano", type: "select", required: true },
  ]);
  await page.goto(`/generators/${gid}/edit`);
  await expect(page.getByTestId("fields-issues")).toContainText("2 campos precisam de atenção");
  const plano = page.getByTestId("field-item").filter({ hasText: "Plano" });
  await expect(plano).toContainText("Lista sem opções");
  await expect(page.getByTestId("field-item").filter({ hasText: "Nome" })).toContainText("Fora do documento");

  // renomeia e troca de campo antes do salvamento automático (700 ms): a alteração é salva ao sair
  await page.getByTestId("field-item").filter({ hasText: "Nome" }).getByRole("button", { name: /^Nome/ }).click();
  await page.getByTestId("field-label").fill("Nome completo");
  await page.getByTestId("back-to-list").click();
  await expect(page.getByTestId("field-list")).toContainText("Nome completo");
  await waitSaved(page);
  await page.reload();
  await expect(page.getByTestId("field-list")).toContainText("Nome completo");

  // a revisão lista as pendências e leva direto ao campo no editor
  await page.goto(`/generators/${gid}/review`);
  const checklist = page.getByTestId("review-checklist");
  await expect(checklist).toContainText("Lista de opções sem nenhuma opção");
  await checklist.getByRole("listitem").filter({ hasText: "Plano" }).getByRole("link", { name: "Corrigir no editor" }).first().click();
  await page.waitForURL(/\/edit\?field=/);
  await expect(page.getByRole("heading", { name: "Configurar “Plano”" })).toBeVisible();
  await page.getByLabel(/Colar várias opções/).fill("Básico\nPremium");
  await page.getByRole("button", { name: "Adicionar linhas" }).click();
  await expect(page.getByTestId("field-save-state")).toHaveText("Alterações salvas.", { timeout: 10_000 });
  await page.getByTestId("back-to-list").click();
  await expect(page.getByTestId("field-item").filter({ hasText: "Plano" })).not.toContainText("Lista sem opções");
});
