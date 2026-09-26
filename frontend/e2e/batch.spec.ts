import { expect, test, type Page } from "@playwright/test";
import { createUsableGenerator, demoGeneratorId, login, readDownload, XLSX } from "./helpers";

async function pasteIntoGrid(page: Page, tsv: string) {
  await page.getByTestId("batch-grid").evaluate((el, text) => {
    const dt = new DataTransfer();
    dt.setData("text/plain", text);
    el.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }));
  }, tsv);
}

// Fluxo 2 — lote: digitar na grade, colar do Excel, importar XLSX com mapeamento, corrigir célula inválida,
// executar em background, acompanhar, baixar ZIP e relatório, consultar histórico.
test("fluxo de lote completo na grade estilo planilha", async ({ page }) => {
  await login(page);
  const id = await demoGeneratorId(page);
  await page.goto(`/generators/${id}/batch`);
  const grid = page.getByTestId("batch-grid");
  await expect(grid).toBeVisible();
  await expect(page.getByRole("columnheader", { name: /Nome do contratante/ })).toBeVisible();

  // ---- 1) digitar direto na grade (3 linhas): clique na célula, digite, Tab/Enter navegam
  await page.getByTestId("cell-0-nome_do_contratante").click();
  await page.keyboard.type("Ana Lima");
  await page.keyboard.press("Tab"); // confirma e vai para a coluna do CPF
  await page.keyboard.type("52998224725");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("cell-0-cpf_do_contratante")).toContainText("529.982.247-25"); // máscara aplicada
  await page.getByTestId("cell-1-nome_do_contratante").click();
  await page.keyboard.type("Bruno Dias");
  await page.keyboard.press("Enter");
  await page.getByTestId("cell-2-nome_do_contratante").click();
  await page.keyboard.type("Carla Nunes");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("cell-1-nome_do_contratante")).toHaveText("Bruno Dias");

  // ---- 2) colar um intervalo copiado do Excel/Sheets (TSV) começando no CPF da linha 2
  await page.getByTestId("cell-1-cpf_do_contratante").click();
  await pasteIntoGrid(page, "11144477735\tSuporte técnico mensal\t1850,5\t15/10/2026\tNão\n39053344705\tTreinamento de equipes\t3200\t03/11/2026\tSim\n");
  await expect(page.getByTestId("cell-1-valor_mensal")).toContainText("1.850,50");
  await expect(page.getByTestId("cell-2-tipo_de_servico")).toContainText("Treinamento de equipes");
  await expect(page.getByTestId("cell-2-cpf_do_contratante")).toContainText("390.533.447-05");

  // ---- 3) importar o XLSX de exemplo (substituindo) com mapeamento de colunas
  await page.getByTestId("open-import").click();
  await page.getByTestId("import-input").setInputFiles(XLSX);
  await expect(page.getByRole("heading", { name: "Mapear colunas" })).toBeVisible();
  await expect(page.getByLabel("Campo para a coluna Nome do contratante")).toHaveValue("nome_do_contratante"); // sugestão automática
  await page.getByLabel("Substituir as linhas atuais").check();
  await page.getByTestId("import-apply").click();
  await expect(page.getByTestId("valid-count")).toHaveText("3 válidas");
  await expect(page.getByTestId("invalid-count")).toHaveText("1 com erro");

  // ---- 4) identificar e corrigir a célula inválida pelo painel de erros
  const errors = page.getByTestId("error-item");
  await expect(errors).toHaveCount(2); // CPF inválido e valor não numérico da linha 4
  await expect(errors.first()).toContainText("Linha 4");
  await errors.filter({ hasText: "CPF" }).click();
  await page.keyboard.type("39053344705");
  await page.keyboard.press("Enter");
  await errors.filter({ hasText: "Valor" }).click();
  await page.keyboard.type("1500");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("invalid-count")).toHaveText("0 com erro");
  await expect(page.getByTestId("valid-count")).toHaveText("4 válidas");
  await expect(page.getByTestId("cell-3-valor_mensal")).toContainText("1.500,00");

  // ---- 5) executar em background, acompanhar e baixar ZIP + relatório
  await page.getByTestId("open-run").click();
  await page.getByTestId("fmt-both").check();
  await page.getByTestId("run-start").click();
  const job = page.getByTestId("job-result");
  await expect(job).toBeVisible();
  await expect(job).toHaveAttribute("data-status", "succeeded", { timeout: 120_000 });
  await expect(job).toContainText("4 de 4 processados");

  const [zipDl] = await Promise.all([page.waitForEvent("download"), page.getByTestId("download-zip").click()]);
  const zip = await readDownload(zipDl);
  expect(zip.subarray(0, 2).toString()).toBe("PK");
  expect(zip.length).toBeGreaterThan(20_000);
  const [csvDl] = await Promise.all([page.waitForEvent("download"), page.getByTestId("download-report").click()]);
  const csv = (await readDownload(csvDl)).toString("utf-8");
  expect(csv).toContain("linha;status;arquivos;codigo_erro;mensagem");
  expect(csv.match(/;gerado;/g)).toHaveLength(4);
  await page.getByRole("button", { name: "Fechar" }).last().click();

  // ---- 6) histórico: o lote aparece, com quantidades e status
  await page.goto("/history");
  const first = page.getByTestId("history-table").locator("tbody tr").first();
  await expect(first).toContainText("Lote");
  await expect(first).toContainText("4/4");
  await expect(first).toContainText("Concluído");
});

test("linhas inválidas bloqueiam o lote; gerar só as válidas exige confirmação explícita", async ({ page }) => {
  await login(page);
  const id = await demoGeneratorId(page);
  await page.goto(`/generators/${id}/batch`);
  await page.getByTestId("cell-0-nome_do_contratante").click();
  await pasteIntoGrid(page, "Ana Lima\t52998224725\tSuporte técnico mensal\t1000\t01/10/2026\tSim\nDiego\t12345678900\tSuporte técnico mensal\t1000\t01/10/2026\tSim\n");
  await expect(page.getByTestId("invalid-count")).toHaveText("1 com erro");
  await page.getByTestId("open-run").click();
  await page.getByTestId("run-start").click(); // "Validar": o servidor confirma o erro e não cria job
  await expect(page.getByText(/1 linha tem erro|1 linha com erro/).first()).toBeVisible();
  await page.getByTestId("only-valid").check();
  await page.getByTestId("run-start").click();
  await expect(page.getByTestId("job-result")).toHaveAttribute("data-status", "partial", { timeout: 60_000 });
  await expect(page.getByTestId("job-result")).toContainText("1 linha ignorada");
});

test("importação com valor novo na lista suspensa oferece adicionar a opção", async ({ page }) => {
  await login(page);
  const gid = await createUsableGenerator(page, "Plano de teste - lote E2E", [
    { label: "Nome", type: "text_short", required: true },
    { label: "Plano", type: "select", required: true, options: [{ label: "Básico" }, { label: "Premium" }] },
  ]);
  await page.goto(`/generators/${gid}/batch`);
  await page.getByTestId("open-import").click();
  await page.getByTestId("import-input").setInputFiles({
    name: "lote.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("Nome,Plano\nAna Lima,Enterprise\nBruno Dias,Básico\n", "utf-8"),
  });
  await expect(page.getByRole("heading", { name: "Mapear colunas" })).toBeVisible();
  await expect(page.getByLabel("Campo para a coluna Nome")).toHaveValue("nome"); // sugestão automática
  await page.getByTestId("import-apply").click();

  // valor "Enterprise" não existe na lista do campo "Plano" → diálogo pergunta se quer adicionar
  await expect(page.getByRole("heading", { name: "Valores novos na lista suspensa" })).toBeVisible();
  await expect(page.getByText("Opções atuais:")).toBeVisible();
  await expect(page.getByText("Básico", { exact: true })).toBeVisible();
  const checkbox = page.getByLabel(/Adicionar .Enterprise. como nova opção/);
  await expect(checkbox).toBeChecked(); // marcado por padrão
  await page.getByTestId("import-add-options").click();

  // depois de adicionada, a linha com "Enterprise" já entra válida (sem precisar corrigir na grade)
  await expect(page.getByTestId("valid-count")).toHaveText("2 válidas");
  await expect(page.getByTestId("invalid-count")).toHaveText("0 com erro");
  await expect(page.getByTestId("cell-0-plano")).toContainText("Enterprise");
});
