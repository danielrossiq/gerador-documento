import { expect, test } from "@playwright/test";

// Landing de venda (/): demonstração sem cadastro, preços e chamadas para o cadastro.
test.describe("landing", () => {
  test("topo vende e leva ao cadastro", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("preenchem sozinhos");
    await expect(page.getByTestId("hero-demo")).toBeVisible();
    await expect(page.getByTestId("hero-cta")).toHaveAttribute("href", "/register");
    await expect(page.getByTestId("header-cta")).toHaveAttribute("href", "/register");
  });

  test("demonstração interativa: IA marca os campos, o documento muda ao digitar e o PDF é gerado", async ({ page }) => {
    await page.goto("/#demo");
    const demo = page.getByTestId("live-demo");
    await demo.getByTestId("demo-analyse").click();
    const name = demo.getByRole("textbox", { name: "Nome do cliente" });
    await expect(name).toBeVisible({ timeout: 10_000 });
    await name.fill("Joana Prado");
    await expect(demo.locator('[data-field="cliente"]').first()).toHaveText("Joana Prado");
    // valor por extenso acompanha o valor digitado (mesma função do produto)
    await demo.getByRole("textbox", { name: "Valor dos honorários" }).fill("1250000");
    await expect(demo.getByText("doze mil e quinhentos reais")).toBeVisible();
    // CPF inválido bloqueia a geração
    const cpf = demo.getByRole("textbox", { name: "CPF do cliente" });
    await cpf.fill("11111111111");
    await expect(demo.getByText("CPF inválido")).toBeVisible();
    await expect(demo.getByTestId("demo-generate")).toBeDisabled();
    await cpf.fill("52998224725");
    await demo.getByTestId("demo-generate").click();
    await expect(demo.getByTestId("demo-done")).toContainText("honorarios-joana-prado.pdf");
  });

  test("preços: alterna mensal/anual e cada plano leva ao cadastro com o plano escolhido", async ({ page }) => {
    await page.goto("/#precos");
    const pricing = page.getByTestId("pricing");
    await expect(pricing.locator('[data-plan="profissional"]')).toContainText("R$ 39,90");
    await pricing.getByRole("radio", { name: "Mensal" }).click();
    await expect(pricing.locator('[data-plan="profissional"]')).toContainText("R$ 49,90");
    await expect(page.getByTestId("plan-cta-profissional")).toHaveAttribute("href", "/register?plano=profissional&ciclo=mensal");
    await expect(page.getByTestId("plan-cta-gratis")).toHaveAttribute("href", "/register?plano=gratis");
  });

  test("páginas legais existem", async ({ page }) => {
    for (const [path, title] of [["/termos", "Termos de uso"], ["/privacidade", "Política de privacidade"]] as const) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(title);
    }
  });
});
