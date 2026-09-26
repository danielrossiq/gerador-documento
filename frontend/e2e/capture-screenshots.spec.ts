import { expect, test } from "@playwright/test";
import path from "node:path";
import { demoGeneratorId, DOCX, login, register, selectText, waitSaved, XLSX } from "./helpers";

// Gera as capturas de docs/screenshots. Não roda na suíte normal:  CAPTURE_SCREENSHOTS=1 npx playwright test e2e/capture-screenshots.spec.ts
const OUT = path.resolve(__dirname, "..", "..", "docs", "screenshots");
const shot = (name: string) => path.join(OUT, `${name}.png`);
test.skip(!process.env.CAPTURE_SCREENSHOTS, "somente sob demanda");
test.setTimeout(240_000);

test("capturas: primeiro acesso, etapas Modelo → Campos → Revisão", async ({ page }) => {
  await register(page, `shots-${Date.now()}@exemplo.test`);
  await page.screenshot({ path: shot("01-primeiro-acesso") });

  await page.getByRole("link", { name: "Criar meu primeiro gerador" }).click();
  await page.getByLabel(/^Nome do gerador/).fill("Contrato de prestação de serviços");
  await page.screenshot({ path: shot("02-etapa-modelo-envio") });
  await page.getByTestId("docx-input").setInputFiles(DOCX);
  await page.waitForURL(/\/generators\/.+\/edit/, { timeout: 60_000 });

  const doc = page.getByTestId("doc-page");
  await expect(doc).toContainText("CONTRATO DE PRESTAÇÃO DE SERVIÇOS");
  await expect(page.getByTestId("suggestion").first()).toBeVisible();
  await page.screenshot({ path: shot("03-etapa-campos-sugestoes") });

  const transform = () => page.getByRole("toolbar", { name: "Ações para o texto selecionado" }).getByRole("button", { name: "Transformar em campo" }).click();
  await selectText(page, "body/p3", "João da Silva");
  await expect(page.getByRole("toolbar", { name: "Ações para o texto selecionado" })).toBeVisible();
  await page.screenshot({ path: shot("04-editor-selecao-menu-flutuante") });
  await transform();
  await page.getByLabel(/^Nome do campo/).fill("Nome do contratante");
  await page.screenshot({ path: shot("05-editor-novo-campo") });
  await page.getByTestId("create-field").click();
  await expect(doc.locator(".field-chip", { hasText: "Nome do contratante" })).toHaveCount(1);

  await selectText(page, "body/p5", "João da Silva");
  await transform();
  await page.getByLabel(/^Nome do campo/).fill("Nome do contratante");
  await expect(page.getByTestId("duplicate-label")).toBeVisible();
  await page.screenshot({ path: shot("06-editor-aviso-nome-repetido") });
  await page.getByTestId("duplicate-label").getByRole("button", { name: "use o campo existente" }).click();

  await selectText(page, "body/p5", "consultoria em desenvolvimento de software");
  await transform();
  await page.getByLabel(/^Nome do campo/).fill("Tipo de serviço");
  await page.getByLabel(/^Tipo$/).selectOption("select");
  await page.getByLabel(/Colar várias opções/).fill("Consultoria em desenvolvimento de software\nSuporte técnico mensal\nTreinamento de equipes");
  await page.getByRole("button", { name: "Adicionar linhas" }).click();
  await page.screenshot({ path: shot("07-editor-lista-de-opcoes") });
  await page.getByTestId("create-field").click();

  await page.getByRole("tab", { name: /Sugestões/ }).click();
  await page.getByTestId("accept-all").click();
  await expect(doc.locator(".field-chip", { hasText: "CPF" })).toHaveCount(1, { timeout: 20_000 });
  await waitSaved(page);
  await page.getByRole("tab", { name: /^Campos/ }).click();
  await page.screenshot({ path: shot("08-editor-lista-de-campos") });
  await doc.locator(".field-chip", { hasText: "Valor" }).first().click();
  await page.screenshot({ path: shot("09-editor-campo-selecionado") });

  await page.getByTestId("go-review").click();
  await page.waitForURL(/\/review$/);
  await expect(page.getByTestId("review-checklist")).toBeVisible();
  await page.screenshot({ path: shot("10-revisao-previa-exemplo") });
});

test("capturas: painel, formulário, lote, importação, histórico", async ({ page }) => {
  await login(page);
  const id = await demoGeneratorId(page);
  await page.screenshot({ path: shot("11-painel") });

  await page.goto(`/generators/${id}/use`);
  await page.getByTestId("field-nome_do_contratante").fill("Maria Aparecida Souza");
  await page.getByTestId("fill-example").click();
  await page.getByTestId("field-cpf_do_contratante").fill("11111111111");
  await page.getByTestId("generate-docx").click();
  await expect(page.getByRole("alert").filter({ hasText: "CPF inválido." }).first()).toBeVisible();
  await page.screenshot({ path: shot("12-formulario-previa-erro") });
  await page.getByRole("button", { name: "Limpar" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Limpar formulário" }).click();

  await page.goto(`/generators/${id}/batch`);
  await page.screenshot({ path: shot("13-lote-vazio") });
  await page.getByTestId("open-import").click();
  await page.getByTestId("import-input").setInputFiles(XLSX);
  await expect(page.getByRole("heading", { name: "Mapear colunas" })).toBeVisible();
  await page.screenshot({ path: shot("14-lote-importacao-mapeamento") });
  await page.getByTestId("import-apply").click();
  await expect(page.getByTestId("invalid-count")).toHaveText("1 com erro");
  await page.screenshot({ path: shot("15-lote-grade-com-erros") });

  await page.getByTestId("open-run").click();
  await page.getByTestId("fmt-both").check();
  await page.screenshot({ path: shot("16-lote-resumo") });
  await page.getByTestId("only-valid").check();
  await page.getByTestId("run-start").click();
  await expect(page.getByTestId("job-result")).toHaveAttribute("data-status", "partial", { timeout: 120_000 });
  await page.screenshot({ path: shot("17-lote-concluido-parcialmente") });
  await page.getByRole("button", { name: "Fechar" }).last().click();

  await page.goto("/history");
  await expect(page.getByTestId("history-table")).toBeVisible();
  await page.screenshot({ path: shot("18-historico") });
});
