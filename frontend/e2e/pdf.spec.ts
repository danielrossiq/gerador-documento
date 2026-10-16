import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { DEMO_DIR, register } from "./helpers";

const DIGITADO = path.join(DEMO_DIR, "contrato_prestacao_servicos.pdf");
const DIGITALIZADO = path.join(DEMO_DIR, "contrato_digitalizado.pdf");

async function pdfImportEnabled(page: import("@playwright/test").Page): Promise<boolean> {
  const me = (await (await page.request.get("/api/v1/auth/me")).json()) as { features?: { pdf_import?: boolean } };
  return me.features?.pdf_import === true;
}

// Piloto (PDF_IMPORT_ENABLED desligado, o padrão): a tela só oferece Word e um PDF é recusado sem criar modelo.
test("com PDF desligado (piloto), a tela só aceita Word e recusa PDF sem deixar modelo órfão", async ({ page }) => {
  await register(page, `e2e-pdf-off-${Date.now()}@exemplo.test`);
  test.skip(await pdfImportEnabled(page), "stack com PDF_IMPORT_ENABLED=true");
  await page.goto("/generators/new");
  await expect(page.getByText(/^Word \(\.docx\) — contrato/)).toBeVisible();
  await expect(page.getByTestId("docx-input")).not.toHaveAttribute("accept", /pdf/);
  await page.getByTestId("docx-input").setInputFiles(DIGITADO);
  await expect(page.getByRole("alert").filter({ hasText: "O envio de PDF está desativado" })).toBeVisible();
  await page.goto("/models");
  await expect(page.getByTestId("generator-card")).toHaveCount(0);
});

// PDF digitado (texto real, exportado do Word/LibreOffice) vira um .docx editável e segue para a etapa Campos;
// PDF digitalizado (imagem, mesmo com camada de OCR) é recusado com explicação e não deixa um modelo órfão.
test("PDF digitado é aceito e convertido; PDF digitalizado é recusado sem deixar modelo órfão", async ({ page }) => {
  expect(fs.existsSync(DIGITADO) && fs.existsSync(DIGITALIZADO), "PDFs de demonstração em demo/").toBe(true);
  await register(page, `e2e-pdf-${Date.now()}@exemplo.test`);
  test.skip(!(await pdfImportEnabled(page)), "PDF_IMPORT_ENABLED desligado (padrão do piloto)");

  // ---- digitalizado: recusa clara na própria tela de envio
  await page.goto("/generators/new");
  await page.getByTestId("docx-input").setInputFiles(DIGITALIZADO);
  const alert = page.getByRole("alert").filter({ hasText: /digitalizado/i });
  await expect(alert).toBeVisible({ timeout: 60_000 });
  await expect(alert).toContainText(/Word|\.docx/);
  await expect(page).toHaveURL(/\/generators\/new/);
  await page.goto("/models");
  await expect(page.getByTestId("generator-card")).toHaveCount(0); // o modelo criado para o envio foi apagado

  // ---- digitado: vira .docx editável e cai na etapa Campos com o conteúdo do contrato
  await page.goto("/generators/new");
  await page.getByTestId("docx-input").setInputFiles(DIGITADO);
  await page.waitForURL(/\/generators\/.+\/edit/, { timeout: 90_000 });
  await expect(page.getByTestId("doc-page")).toContainText(/CONTRATO/i);
  await expect(page.getByTestId("doc-page")).toContainText("João da Silva");

  // a etapa Documento diz que o arquivo veio de PDF e mantém o nome do arquivo enviado
  await page.goto(page.url().replace(/\/edit.*$/, "/template"));
  await expect(page.getByTestId("current-file")).toContainText("contrato_prestacao_servicos.pdf");
  await expect(page.getByTestId("current-file")).toContainText("convertido de PDF para Word");
});
