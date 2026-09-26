import { expect, test } from "@playwright/test";
import { DOCX, readDownload, register, selectText, waitSaved } from "./helpers";

// Fluxo 1 — do zero: cadastro → gerador → upload → selecionar "João da Silva" → Transformar em campo → lista suspensa →
// usar agora (sem etapa de publicação) → formulário → DOCX e PDF válidos → histórico.
test("fluxo individual completo: selecionar texto, criar campos e gerar DOCX/PDF", async ({ page }) => {
  const email = `e2e-${Date.now()}@exemplo.test`;
  await register(page, email);
  await expect(page.getByRole("heading", { name: "Crie seu primeiro gerador" })).toBeVisible();

  // ---- assistente: nome → upload → análise
  await page.getByRole("link", { name: "Novo gerador" }).first().click();
  await page.getByLabel(/^Nome do gerador/).fill("Contrato de prestação de serviços");
  await page.getByLabel(/^Descrição curta/).fill("Modelo para o teste E2E");
  await page.getByRole("button", { name: "Continuar" }).click();
  await page.getByTestId("docx-input").setInputFiles(DOCX);
  await expect(page.getByTestId("picked-file")).toContainText("contrato_prestacao_servicos.docx");
  await page.getByRole("button", { name: "Enviar e analisar" }).click();
  await page.waitForURL(/\/generators\/.+\/edit/, { timeout: 60_000 });

  // ---- editor: o conteúdo do DOCX aparece (cabeçalho, corpo, tabela, rodapé)
  const doc = page.getByTestId("doc-page");
  await expect(doc).toContainText("CONTRATO DE PRESTAÇÃO DE SERVIÇOS");
  await expect(doc.locator("table")).toHaveCount(1);
  await expect(doc.locator('section[data-kind="header"]')).toBeVisible();
  await expect(doc.locator('section[data-kind="footer"]')).toBeVisible();
  await expect(page.getByText(/Sugestões locais \(IA externa não configurada\)|IA externa/)).toBeVisible();

  // ---- selecionar "João da Silva" → menu flutuante → Transformar em campo
  await selectText(page, "body/p3", "João da Silva");
  const toolbar = page.getByRole("toolbar", { name: "Ações para o texto selecionado" });
  await expect(toolbar).toBeVisible();
  await toolbar.getByRole("button", { name: "Transformar em campo" }).click();
  await expect(page.getByTestId("selected-text")).toHaveText("“João da Silva”");
  await page.getByLabel(/^Nome do campo/).fill("Nome do contratante");
  await page.getByRole("button", { name: "Criar campo" }).click();
  const chip = doc.locator(".field-chip", { hasText: "Nome do contratante" });
  await expect(chip).toHaveCount(1);
  await expect(chip).toHaveAttribute("data-tooltip", /Tipo: Texto curto/);

  // ---- reutilizar o mesmo campo em outra ocorrência ("em favor de João da Silva")
  await selectText(page, "body/p5", "João da Silva");
  await page.getByRole("toolbar", { name: "Ações para o texto selecionado" }).getByRole("button", { name: "Transformar em campo" }).click();
  const existing = page.locator("details", { hasText: "Ou usar um campo que já existe" });
  await existing.locator("summary").click();
  await existing.getByRole("button", { name: "Nome do contratante", exact: true }).click();
  await expect(doc.locator(".field-chip", { hasText: "Nome do contratante" })).toHaveCount(2);

  // ---- lista suspensa "Tipo de serviço" com opções coladas (uma por linha)
  await selectText(page, "body/p5", "consultoria em desenvolvimento de software");
  await page.getByRole("toolbar", { name: "Ações para o texto selecionado" }).getByRole("button", { name: "Transformar em campo" }).click();
  await page.getByLabel(/^Nome do campo/).fill("Tipo de serviço");
  await page.getByLabel(/^Tipo$/).selectOption("select");
  await page.getByLabel(/Colar várias opções/).fill("Consultoria em desenvolvimento de software\nSuporte técnico mensal\nTreinamento de equipes");
  await page.getByRole("button", { name: "Adicionar linhas" }).click();
  await expect(page.getByRole("textbox", { name: "Opção 3", exact: true })).toHaveValue("Treinamento de equipes");
  await page.getByRole("button", { name: "Criar campo" }).click();
  await expect(doc.locator(".field-chip", { hasText: "Tipo de serviço" })).toHaveCount(1);

  // ---- demais campos: aceitar sugestões de alta confiança (CPF, CNPJ, valor, data)
  await page.getByRole("tab", { name: /Sugestões/ }).click();
  await page.getByRole("button", { name: /Aceitar alta confiança/ }).click();
  await expect(doc.locator(".field-chip", { hasText: "CPF" })).toHaveCount(1, { timeout: 20_000 });
  await expect(doc.locator(".field-chip", { hasText: "Valor" })).toHaveCount(2);
  await waitSaved(page);

  // ---- sem etapa de publicação: o gerador já está pronto para uso
  await page.getByRole("button", { name: "Usar agora" }).click();

  // ---- formulário individual com prévia ao vivo
  await page.waitForURL(/\/use$/);
  await page.getByTestId("field-nome_do_contratante").fill("Maria Aparecida Souza");
  await expect(page.getByTestId("doc-preview")).toContainText("Maria Aparecida Souza");
  await page.getByTestId("field-cpf_contratante").fill("52998224725");
  await expect(page.getByTestId("field-cpf_contratante")).toHaveValue("529.982.247-25"); // máscara
  await page.getByTestId("field-tipo_de_servico").selectOption({ label: "Suporte técnico mensal" });
  // erro em texto ao lado do campo (validação brasileira)
  await page.getByTestId("field-cpf_contratante").fill("11111111111");
  await page.getByTestId("generate-docx").click();
  await expect(page.getByRole("alert").filter({ hasText: "CPF inválido." }).first()).toBeVisible();
  await page.getByTestId("field-cpf_contratante").fill("52998224725");
  await page.getByTestId("field-valor").fill("1234,5");
  // o documento tem duas datas distintas ("01/10/2026" e "21 de setembro de 2026" na assinatura) — a
  // detecção automática agora numera sugestões duplicadas do mesmo campo-base ("Data 1"/"Data 2")
  await page.getByTestId("field-data_1").fill("2026-11-15");
  await page.getByTestId("field-data_2").fill("2026-11-20");

  // ---- gerar DOCX e PDF (arquivos válidos)
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

  // ---- histórico
  await page.goto("/history");
  const rows = page.getByTestId("history-table").locator("tbody tr");
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText("Concluído");
  await expect(rows.first()).toContainText("Contrato de prestação de serviços");
});
