import { expect, test } from "@playwright/test";
import path from "node:path";
import { register } from "./helpers";

const DOC = path.join(__dirname, "fixtures", "honorarios_extenso.docx");

// "R$ 5.000,00 (cinco mil reais)" no documento: a sugestão já vem como um campo Valor com extenso, a prévia
// mostra o extenso gerado e o formulário do campo deixa trocar o formato.
test("valor com extenso no documento vira campo Valor com extenso", async ({ page }) => {
  await register(page, `e2e-extenso-${Date.now()}@exemplo.test`);
  await page.goto("/generators/new");
  await page.getByTestId("docx-input").setInputFiles(DOC);
  await page.waitForURL(/\/generators\/.+\/edit/, { timeout: 60_000 });

  const sug = page.getByTestId("suggestion").filter({ hasText: "cinco mil reais" });
  await expect(sug).toBeVisible();
  await sug.getByRole("button", { name: /^Aceitar “R\$ 5\.000,00 \(cinco mil reais\)”/ }).click();
  await expect(page.getByTestId("doc-page").locator(".field-chip", { hasText: "Valor" })).toHaveCount(1);
  await expect(page.getByTestId("doc-page")).not.toContainText("cinco mil reais");

  await page.goto(page.url().replace(/\/edit.*$/, "/review"));
  await page.getByTestId("pv-example").check({ force: true });
  await expect(page.getByRole("region", { name: "Prévia do documento (área rolável)" })).toContainText("R$ 5.000,00 (cinco mil reais)");

  // o formato aparece (e pode ser trocado) na configuração do campo
  await page.goto(page.url().replace(/\/review.*$/, "/edit"));
  await page.getByTestId("field-item").filter({ hasText: "Valor" }).getByRole("button", { name: /^Valor/ }).click();
  await page.getByText("Mais opções").click();
  await expect(page.getByLabel("Como o valor sai no documento")).toHaveValue("words");
});
