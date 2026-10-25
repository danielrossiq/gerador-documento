import { expect, test } from "@playwright/test";
import path from "node:path";
import { demoGeneratorId, login } from "./helpers";

// "Preencher com IA" a partir das FOTOS dos documentos do cliente (D36). Imagens fictícias geradas para teste
// (e2e/fixtures/*_ficticia.jpg). Só roda com a IA ligada no stack; cada execução custa ~US$ 0,001.
const FIX = path.resolve(__dirname, "fixtures");

test("preencher com a foto do comprovante e da ficha do cliente", async ({ page }) => {
  await login(page);
  const status = await (await page.request.get("/api/v1/assist/status")).json();
  test.skip(!status.enabled, "IA desligada neste stack");
  const id = await demoGeneratorId(page);
  await page.goto(`/generators/${id}/use`);
  await page.evaluate((k) => localStorage.removeItem(k), `minuta:form:${id}`);
  await page.reload();

  await page.getByTestId("ai-fill").getByRole("button", { name: /Preencher com IA/ }).click();
  await page.getByTestId("ai-fill-mode-arquivos").click();
  await expect(page.getByTestId("ai-fill-run")).toBeDisabled(); // sem arquivo ainda
  await page.getByTestId("ai-fill-files").setInputFiles([
    path.join(FIX, "conta_de_luz_ficticia.jpg"),
    path.join(FIX, "ficha_cadastral_ficticia.jpg"),
  ]);
  await expect(page.getByTestId("ai-fill-file-list").locator("li")).toHaveCount(2);
  await page.getByTestId("ai-fill-run").click();
  await expect(page.getByText(/campos? preenchidos? pela IA/)).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/Lidos: .+/).first()).toBeVisible();
  // nome e CPF vieram das fotos; o CPF passa na validação (dígitos verificadores)
  await expect(page.locator('input[value*="RENATA" i]').first()).toBeVisible();
  await expect(page.locator('input[value="111.444.777-35"]').first()).toBeVisible();
});
