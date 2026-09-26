import { expect, test } from "@playwright/test";
import path from "node:path";
import { demoGeneratorId, DOCX, login, register, selectText, waitSaved, XLSX } from "./helpers";

// Gera as capturas de docs/screenshots. Não roda na suíte normal:  CAPTURE_SCREENSHOTS=1 npx playwright test e2e/capture-screenshots.spec.ts
const OUT = path.resolve(__dirname, "..", "..", "docs", "screenshots");
const shot = (name: string) => path.join(OUT, `${name}.png`);
test.skip(!process.env.CAPTURE_SCREENSHOTS, "somente sob demanda");
test.setTimeout(240_000);

test("capturas: editor (seleção → campo), sugestões, lista suspensa", async ({ page }) => {
  await register(page, `shots-${Date.now()}@exemplo.test`);
  await page.screenshot({ path: shot("01-painel-vazio") });

  await page.getByRole("link", { name: "Novo gerador" }).first().click();
  await page.getByLabel(/^Nome do gerador/).fill("Contrato de prestação de serviços");
  await page.getByLabel(/^Descrição curta/).fill("Modelo padrão para contratação de serviços recorrentes");
  await page.getByRole("button", { name: "Continuar" }).click();
  await page.getByTestId("docx-input").setInputFiles(DOCX);
  await page.screenshot({ path: shot("02-assistente-upload") });
  await page.getByRole("button", { name: "Enviar e analisar" }).click();
  await page.waitForURL(/\/generators\/.+\/edit/, { timeout: 60_000 });

  const doc = page.getByTestId("doc-page");
  await expect(doc).toContainText("CONTRATO DE PRESTAÇÃO DE SERVIÇOS");
  await expect(page.getByTestId("suggestion").first()).toBeVisible();
  await page.screenshot({ path: shot("03-editor-sugestoes") });

  await selectText(page, "body/p3", "João da Silva");
  await expect(page.getByRole("toolbar", { name: "Ações para o texto selecionado" })).toBeVisible();
  await page.screenshot({ path: shot("04-editor-selecao-menu-flutuante") });
  await page.getByRole("toolbar", { name: "Ações para o texto selecionado" }).getByRole("button", { name: "Transformar em campo" }).click();
  await page.getByLabel(/^Nome do campo/).fill("Nome do contratante");
  await page.screenshot({ path: shot("05-editor-novo-campo") });
  await page.getByRole("button", { name: "Criar campo" }).click();
  await expect(doc.locator(".field-chip", { hasText: "Nome do contratante" })).toHaveCount(1);

  await selectText(page, "body/p5", "consultoria em desenvolvimento de software");
  await page.getByRole("toolbar", { name: "Ações para o texto selecionado" }).getByRole("button", { name: "Transformar em campo" }).click();
  await page.getByLabel(/^Nome do campo/).fill("Tipo de serviço");
  await page.getByLabel(/^Tipo$/).selectOption("select");
  await page.getByLabel(/Colar várias opções/).fill("Consultoria em desenvolvimento de software\nSuporte técnico mensal\nTreinamento de equipes");
  await page.getByRole("button", { name: "Adicionar linhas" }).click();
  await page.screenshot({ path: shot("06-editor-lista-suspensa") });
  await page.getByRole("button", { name: "Criar campo" }).click();

  await page.getByRole("tab", { name: /Sugestões/ }).click();
  await page.getByRole("button", { name: /Aceitar alta confiança/ }).click();
  await expect(doc.locator(".field-chip", { hasText: "CPF" })).toHaveCount(1, { timeout: 20_000 });
  await waitSaved(page);
  await page.getByRole("tab", { name: "Campo", exact: true }).click();
  await doc.locator(".field-chip", { hasText: "Valor" }).first().click();
  await page.screenshot({ path: shot("07-editor-campos-chips-e-painel") });
});

test("capturas: formulário, lote, importação, histórico", async ({ page }) => {
  await login(page);
  const id = await demoGeneratorId(page);
  await page.screenshot({ path: shot("08-painel") });

  await page.goto(`/generators/${id}/use`);
  await page.getByTestId("field-nome_do_contratante").fill("Maria Aparecida Souza");
  await page.getByTestId("field-cpf_do_contratante").fill("52998224725");
  await page.getByTestId("field-tipo_de_servico").selectOption({ label: "Suporte técnico mensal" });
  await page.getByTestId("field-valor_mensal").fill("1234,5");
  await page.getByTestId("field-data_de_inicio").fill("2026-11-15");
  await page.getByTestId("field-cpf_do_contratante").fill("11111111111");
  await page.getByTestId("generate-docx").click();
  await expect(page.getByRole("alert").filter({ hasText: "CPF inválido." }).first()).toBeVisible();
  await page.screenshot({ path: shot("09-formulario-previa-erro") });

  await page.goto(`/generators/${id}/batch`);
  await page.getByTestId("open-import").click();
  await page.getByTestId("import-input").setInputFiles(XLSX);
  await expect(page.getByRole("heading", { name: "Mapear colunas" })).toBeVisible();
  await page.screenshot({ path: shot("10-lote-importacao-mapeamento") });
  await page.getByTestId("import-apply").click();
  await expect(page.getByTestId("invalid-count")).toHaveText("1 com erro");
  await page.screenshot({ path: shot("11-lote-grade-com-erros") });

  await page.getByTestId("open-run").click();
  await page.getByTestId("fmt-both").check();
  await page.screenshot({ path: shot("12-lote-confirmacao") });
  await page.getByTestId("only-valid").check();
  await page.getByTestId("run-start").click();
  await expect(page.getByTestId("job-result")).toHaveAttribute("data-status", "partial", { timeout: 120_000 });
  await page.screenshot({ path: shot("13-lote-concluido-parcialmente") });
  await page.getByRole("button", { name: "Fechar" }).last().click();

  await page.goto("/history");
  await expect(page.getByTestId("history-table")).toBeVisible();
  await page.screenshot({ path: shot("14-historico") });
});
