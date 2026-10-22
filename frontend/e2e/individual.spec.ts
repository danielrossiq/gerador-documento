import { expect, test } from "@playwright/test";
import { DOCX, readDownload, register, selectText, waitSaved } from "./helpers";

async function transformSelection(page: import("@playwright/test").Page) {
  const toolbar = page.getByRole("toolbar", { name: "Ações para o texto selecionado" });
  await expect(toolbar).toBeVisible();
  await toolbar.getByRole("button", { name: "Transformar em campo" }).click();
}

// Fluxo 1 — do zero, pelas 4 etapas: Documento (upload) → Campos (selecionar → Transformar em campo, reaproveitar,
// lista de opções, sugestões) → Revisão (pendências + prévia com dados de exemplo) → Gerar (formulário, rascunho
// automático, Word e PDF válidos) → histórico.
test("fluxo individual completo pelas etapas Documento → Campos → Revisão → Gerar", async ({ page }) => {
  const email = `e2e-${Date.now()}@exemplo.test`;
  await register(page, email);

  // ---- primeiro acesso: o Início explica as etapas e oferece enviar o documento ali mesmo
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/Olá|Início/);
  await expect(page.getByTestId("onboarding")).toBeVisible();
  await expect(page.getByTestId("home-new-model")).toBeVisible();
  await page.goto("/generators/new");

  // ---- etapa 1 (Documento): nome opcional + upload → análise → etapa Campos
  await expect(page.getByRole("navigation", { name: "Etapas do modelo" }).locator('[aria-current="step"]')).toContainText("Documento");
  await page.getByLabel(/^Nome do modelo/).fill("Contrato de prestação de serviços");
  await page.getByTestId("docx-input").setInputFiles(DOCX);
  await page.waitForURL(/\/generators\/.+\/edit/, { timeout: 60_000 });

  // ---- etapa 2 (Campos): o conteúdo do DOCX aparece (cabeçalho, corpo, tabela, rodapé)
  const doc = page.getByTestId("doc-page");
  await expect(doc).toContainText("CONTRATO DE PRESTAÇÃO DE SERVIÇOS");
  await expect(doc.locator("table")).toHaveCount(1);
  await expect(doc.locator('section[data-kind="header"]')).toBeVisible();
  await expect(doc.locator('section[data-kind="footer"]')).toBeVisible();
  await expect(page.locator('[aria-current="step"]')).toContainText("Campos");
  await expect(page.getByTestId("go-review")).toBeDisabled(); // sem campos ainda não dá para revisar

  // ---- selecionar "João da Silva" → menu flutuante → Transformar em campo
  await selectText(page, "body/p3", "João da Silva");
  await transformSelection(page);
  await expect(page.getByTestId("selected-text")).toHaveText("“João da Silva”");
  await page.getByLabel(/^Nome do campo/).fill("Nome do contratante");
  await page.getByTestId("create-field").click();
  const chip = doc.locator(".field-chip", { hasText: "Nome do contratante" });
  await expect(chip).toHaveCount(1);
  await expect(chip).toHaveAttribute("data-tooltip", /Tipo: Texto curto/);

  // ---- mesmo nome em outro trecho: o editor avisa e oferece usar o campo existente
  await selectText(page, "body/p5", "João da Silva");
  await transformSelection(page);
  await page.getByLabel(/^Nome do campo/).fill("nome do CONTRATANTE");
  await expect(page.getByTestId("duplicate-label")).toBeVisible();
  await page.getByTestId("duplicate-label").getByRole("button", { name: "use o campo existente" }).click();
  await expect(doc.locator(".field-chip", { hasText: "Nome do contratante" })).toHaveCount(2);

  // ---- lista de opções: não deixa criar vazia; com opções coladas (uma por linha), cria
  await selectText(page, "body/p5", "consultoria em desenvolvimento de software");
  await transformSelection(page);
  await page.getByLabel(/^Nome do campo/).fill("Tipo de serviço");
  await page.getByLabel(/^Tipo$/).selectOption("select");
  await page.getByTestId("create-field").click();
  await expect(page.getByRole("alert").filter({ hasText: "Adicione pelo menos uma opção" })).toBeVisible();
  await page.getByLabel(/Colar várias opções/).fill("Consultoria em desenvolvimento de software\nSuporte técnico mensal\nTreinamento de equipes");
  await page.getByRole("button", { name: "Adicionar linhas" }).click();
  await expect(page.getByRole("textbox", { name: "Opção 3", exact: true })).toHaveValue("Treinamento de equipes");
  await page.getByTestId("create-field").click();
  await expect(doc.locator(".field-chip", { hasText: "Tipo de serviço" })).toHaveCount(1);

  // ---- demais campos: aceitar as sugestões recomendadas (CPF, CNPJ, valor, datas)
  await page.getByRole("tab", { name: /Sugestões/ }).click();
  await expect(page.getByText(/Sugestões automáticas|IA/).first()).toBeVisible();
  await page.getByTestId("accept-all").click();
  await expect(doc.locator(".field-chip", { hasText: "CPF" })).toHaveCount(1, { timeout: 20_000 });
  await expect(doc.locator(".field-chip", { hasText: "Valor" })).toHaveCount(2);
  await waitSaved(page);

  // ---- a lista de campos acompanha a ordem do documento e mostra que está tudo configurado
  await page.getByRole("tab", { name: /^Campos/ }).click();
  await page.getByTestId("back-to-list").click().catch(() => undefined);
  await expect(page.getByTestId("field-list")).toBeVisible();
  await expect(page.getByText("Mesma ordem do documento", { exact: false })).toBeVisible();
  await expect(page.getByTestId("field-list")).toContainText("Nome do contratante");

  // ---- etapa 3 (Revisão): pendências + prévia com dados de exemplo (o texto original do documento)
  await page.getByTestId("go-review").click();
  await page.waitForURL(/\/review$/);
  await expect(page.getByTestId("review-checklist")).toContainText("campos");
  const preview = page.getByTestId("doc-preview");
  await expect(preview.getByTestId("pv-field").filter({ hasText: "João da Silva" }).first()).toBeVisible();
  await page.getByText("Com os nomes dos campos").click();
  await expect(preview).toContainText("[Nome do contratante]");

  // ---- etapa 4 (Gerar): formulário na ordem do documento, com prévia ao vivo
  await page.getByTestId("review-go-use").click();
  await page.waitForURL(/\/use$/);
  await page.getByTestId("field-nome_do_contratante").fill("Maria Aparecida Souza");
  await expect(page.getByTestId("doc-preview")).toContainText("Maria Aparecida Souza");
  await page.getByTestId("field-cpf_contratante").fill("52998224725");
  await expect(page.getByTestId("field-cpf_contratante")).toHaveValue("529.982.247-25"); // máscara
  await page.getByTestId("field-tipo_de_servico").selectOption({ label: "Suporte técnico mensal" });
  // erro em texto embaixo do campo e na lista de erros (validação brasileira)
  await page.getByTestId("field-cpf_contratante").fill("11111111111");
  await page.getByTestId("generate-docx").click();
  await expect(page.getByRole("alert").filter({ hasText: "CPF inválido." }).first()).toBeVisible();
  await page.getByTestId("field-cpf_contratante").fill("52998224725");
  // "Preencher com dados de exemplo" completa só o que está vazio (valor, datas…)
  await page.getByTestId("fill-example").click();
  await expect(page.getByTestId("field-nome_do_contratante")).toHaveValue("Maria Aparecida Souza");
  // nomes "data_1"/"valor" (só regras) ou "data_inicio"/"valor_mensal" (com IA): o teste vale nos dois stacks
  await expect(page.locator('[data-testid^="field-data"]').first()).toHaveValue("2026-10-01"); // do texto original "01/10/2026"
  await page.locator('[data-testid^="field-valor"]').first().fill("1234,5");

  // ---- rascunho automático: recarregar a página não perde o que foi digitado
  await expect(page.getByTestId("draft-state")).toContainText("Rascunho salvo", { timeout: 10_000 });
  await page.reload();
  await expect(page.getByText("Continuando de onde você parou")).toBeVisible();
  await expect(page.getByTestId("field-nome_do_contratante")).toHaveValue("Maria Aparecida Souza");

  // ---- gerar Word e PDF (arquivos válidos)
  await page.getByTestId("generate-docx").click();
  await expect(page.getByTestId("job-result")).toHaveAttribute("data-status", "succeeded", { timeout: 60_000 });
  const [dlDocx] = await Promise.all([page.waitForEvent("download"), page.getByTestId("download-docx").click()]);
  const docx = await readDownload(dlDocx);
  expect(docx.subarray(0, 2).toString()).toBe("PK");
  expect(docx.length).toBeGreaterThan(5_000);
  await page.getByRole("button", { name: "Fechar" }).last().click();

  await page.getByTestId("generate-pdf").click();
  await expect(page.getByTestId("job-result")).toHaveAttribute("data-status", "succeeded", { timeout: 90_000 });
  const [dlPdf] = await Promise.all([page.waitForEvent("download"), page.getByTestId("download-pdf").click()]);
  const pdf = await readDownload(dlPdf);
  expect(pdf.subarray(0, 5).toString()).toBe("%PDF-");
  expect(pdf.length).toBeGreaterThan(5_000);
  await page.getByRole("button", { name: "Fechar" }).last().click();

  // ---- limpar o formulário pede confirmação
  await page.getByRole("button", { name: "Limpar" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Limpar formulário" }).click();
  await expect(page.getByTestId("field-nome_do_contratante")).toHaveValue("");

  // ---- histórico
  await page.goto("/history");
  const rows = page.getByTestId("history-table").locator("tbody tr");
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText("Concluído");
  await expect(rows.first()).toContainText("Contrato de prestação de serviços");

  // ---- lista de modelos: o modelo aparece como pronto para gerar
  await page.goto("/models");
  await expect(page.getByTestId("generator-card").first()).toContainText("Pronto para gerar");
});

// Um modelo sem documento não leva a uma tela de erro: a lista manda para a etapa Documento, que aceita o envio.
test("modelo sem documento: a lista leva à etapa Documento e o envio conclui a etapa", async ({ page }) => {
  await register(page, `e2e-sem-doc-${Date.now()}@exemplo.test`);
  const csrf = (await page.context().cookies()).find((c) => c.name === "minuta_csrf")?.value ?? "";
  await page.request.post("/api/v1/generators", { data: { name: "Sem documento E2E" }, headers: { "X-CSRF-Token": csrf } });
  await page.goto("/models");
  const card = page.getByTestId("generator-card").filter({ hasText: "Sem documento E2E" });
  await expect(card.getByTestId("generator-status")).toHaveText("Falta o documento");
  await card.getByRole("link", { name: "Enviar documento" }).click();
  await page.waitForURL(/\/template$/);
  await expect(page.getByText("Este modelo ainda não tem documento")).toBeVisible();
  await page.getByTestId("docx-input").setInputFiles(DOCX);
  await page.waitForURL(/\/edit/, { timeout: 60_000 });
  await expect(page.getByTestId("doc-page")).toContainText("CONTRATO");

  // trocar o documento depois: a etapa Documento mostra o arquivo em uso e aceita um novo
  await page.goto(page.url().replace(/\/edit.*$/, "/template"));
  await expect(page.getByTestId("current-file")).toContainText("contrato_prestacao_servicos.docx");
});
