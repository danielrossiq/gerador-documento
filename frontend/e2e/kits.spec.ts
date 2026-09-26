import { expect, test } from "@playwright/test";
import { createUsableGenerator, readDownload, register } from "./helpers";

// Fluxo de kit: dois geradores prontos com campos em comum (nome, CPF) e um campo exclusivo de um deles (cargo) →
// kit → adicionar os dois documentos → detectar campos compartilhados automaticamente → preencher uma vez →
// gerar os dois documentos → baixar tudo em ZIP (e o relatório em CSV).
test("fluxo de kit: campos compartilhados detectados automaticamente, geração e download em ZIP", async ({ page }) => {
  const email = `e2e-kit-${Date.now()}@exemplo.test`;
  await register(page, email);

  await createUsableGenerator(page, "Contrato A - Kit E2E", [
    { label: "Nome completo", type: "text_short", required: true },
    { label: "CPF", type: "text_short", required: true },
  ]);
  await createUsableGenerator(page, "Contrato B - Kit E2E", [
    { label: "Nome completo", type: "text_short", required: true },
    { label: "CPF", type: "text_short", required: true },
    { label: "Cargo", type: "text_short", required: false },
  ]);

  // ---- criar o kit
  await page.goto("/kits");
  await page.getByRole("link", { name: "Novo kit" }).click();
  await page.getByLabel(/^Nome do kit/).fill("Kit de admissão E2E");
  await page.getByRole("button", { name: "Continuar" }).click();
  await page.waitForURL(/\/kits\/.+\/edit/);

  // ---- adicionar os dois documentos
  for (const name of ["Contrato A - Kit E2E", "Contrato B - Kit E2E"]) {
    await page.getByRole("button", { name: "Adicionar documento" }).first().click();
    const dialog = page.getByRole("dialog", { name: "Adicionar documento ao kit" });
    await dialog.getByRole("listitem").filter({ hasText: name }).getByRole("button", { name: "Adicionar" }).click();
    await expect(dialog).toBeHidden();
  }
  await expect(page.getByRole("listitem").filter({ hasText: "Contrato A - Kit E2E" })).toBeVisible();
  await expect(page.getByRole("listitem").filter({ hasText: "Contrato B - Kit E2E" })).toBeVisible();

  // ---- detectar automaticamente: "Nome completo" e "CPF" viram campos do kit; "Cargo" fica só no documento B
  const [autoDetectResp] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/auto-detect") && r.request().method() === "POST"),
    page.getByRole("button", { name: "Detectar automaticamente" }).click(),
  ]);
  expect(autoDetectResp.ok()).toBeTruthy();
  await expect(page.getByRole("listitem").filter({ hasText: "Nome completo" })).toBeVisible();
  await expect(page.getByRole("listitem").filter({ hasText: /^CPF/ })).toBeVisible();
  await expect(page.getByRole("listitem").filter({ hasText: "Cargo" })).toHaveCount(0);

  // ---- usar o kit
  await page.getByRole("link", { name: "Usar agora" }).click();
  await page.waitForURL(/\/kits\/.+\/use$/);

  await page.getByTestId("field-nome_completo").fill("Maria de Testes E2E");
  await page.getByTestId("field-cpf").fill("12345678901");
  await expect(page.getByText(/Só em .Contrato B - Kit E2E./)).toBeVisible();
  await page.getByTestId("field-cargo").fill("Analista de Operações");

  await page.getByTestId("generate-kit").click();
  await expect(page.getByTestId("kit-run-result")).toHaveAttribute("data-status", "succeeded", { timeout: 60_000 });

  // ---- baixar tudo em ZIP e o relatório em CSV
  const [dlZip] = await Promise.all([page.waitForEvent("download"), page.getByTestId("kit-download-zip").click()]);
  const zip = await readDownload(dlZip);
  expect(zip.subarray(0, 2).toString()).toBe("PK");
  expect(zip.length).toBeGreaterThan(1_000);

  const [dlReport] = await Promise.all([page.waitForEvent("download"), page.getByTestId("kit-download-report").click()]);
  const report = await readDownload(dlReport);
  expect(report.toString("utf-8")).toContain("Contrato A - Kit E2E");
  expect(report.toString("utf-8")).toContain("Contrato B - Kit E2E");

  // ---- também é possível baixar cada documento do kit separadamente
  const [dlSingle] = await Promise.all([page.waitForEvent("download"), page.getByTestId("kit-member-0-download-docx").click()]);
  const single = await readDownload(dlSingle);
  expect(single.subarray(0, 2).toString()).toBe("PK");
});
