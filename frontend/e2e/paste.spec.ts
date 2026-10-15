import { expect, test } from "@playwright/test";
import { login } from "./helpers";

const comTitulos = [
  "Nome do contratante\tCPF do contratante\tValor mensal\tData de início",
  "Maria Souza\t529.982.247-25\t1.500,00\t01/02/2027",
  "João Lima\t111.444.777-35\t900,00\t15/03/2027",
].join("\n");

const semTitulos = [
  "Maria Souza\t529.982.247-25\t1.500,00\t01/02/2027",
  "João Lima\t111.444.777-35\t900,00\t15/03/2027",
].join("\n");

async function paste(page: import("@playwright/test").Page, text: string) {
  await page.goto("/dashboard");
  const area = page.getByTestId("paste-area");
  await expect(area).toBeVisible();
  await area.fill(text);
}

test("colar com títulos identifica o modelo e leva as linhas para o lote", async ({ page }) => {
  await login(page);
  await paste(page, comTitulos);
  await expect(page.getByTestId("paste-result")).toBeVisible();
  await expect(page.getByText(/Contrato de presta/).first()).toBeVisible();
  await expect(page.getByText("A primeira linha parece ser dado, não título")).toHaveCount(0);
  await page.getByTestId("paste-go").click();
  await page.waitForURL(/\/generators\/.+\/batch/);
  await expect(page.getByTestId("batch-grid")).toBeVisible();
  await expect(page.getByText(/2 linhas coladas na planilha/)).toBeVisible();
  await expect(page.getByTestId("batch-grid")).toContainText("Maria Souza");
  await expect(page.getByTestId("batch-grid")).toContainText("João Lima");
});

test("colar sem linha de títulos avisa e leva a 1ª linha como dado (nada vai a serviço externo)", async ({ page }) => {
  await login(page);
  await paste(page, semTitulos);
  await expect(page.getByTestId("paste-result")).toBeVisible();
  await expect(page.getByText("A primeira linha parece ser dado, não título")).toBeVisible();
  // a 1ª linha não é tratada como título de coluna: nenhum campo é reconhecido por nome/IA
  await expect(page.getByText(/parte das correspondências veio da IA/)).toHaveCount(0);
  // só pelo conteúdo, com mais de um campo de data, o modelo não é escolhido sozinho: a pessoa escolhe
  const verdict = page.getByText(/Sem títulos não dá para descobrir o modelo sozinho|Parece ser o modelo|Encontramos o modelo/);
  await expect(verdict).toBeVisible();
  if (await page.getByText("Sem títulos não dá para descobrir o modelo sozinho").isVisible()) {
    await page.getByLabel("Escolher o modelo manualmente").selectOption({ label: "Contrato de prestação de serviços" });
  }
  await expect(page.getByTestId("paste-go")).toBeVisible();
  await page.getByTestId("paste-go").click();
  await page.waitForURL(/\/generators\/.+\/batch/);
  await expect(page.getByTestId("batch-grid")).toContainText("529.982.247-25");
  await expect(page.getByTestId("batch-grid")).toContainText("111.444.777-35");
});
