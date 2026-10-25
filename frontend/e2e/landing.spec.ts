import { expect, test } from "@playwright/test";

// Landing de venda (/): demonstração sem cadastro, preços e chamadas para o cadastro.
test.describe("landing", () => {
  test("topo vende e leva ao cadastro", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Documento feito");
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

  test("vídeo do app de verdade carrega (pôster + MP4)", async ({ page }) => {
    await page.goto("/");
    const video = page.getByTestId("demo-video");
    await video.scrollIntoViewIfNeeded();
    await expect(video).toBeVisible();
    const poster = await video.getAttribute("poster");
    expect((await page.request.get(poster!)).ok()).toBe(true);
    const mp4 = await video.locator('source[type="video/mp4"]').getAttribute("src");
    const r = await page.request.get(mp4!);
    expect(r.ok()).toBe(true);
    expect(r.headers()["content-type"]).toContain("video/mp4");
  });

  test("marca DocFeito: logo, título da aba, favicon e imagem de compartilhamento", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveTitle(/DocFeito/);
    await expect(page.getByRole("banner").getByText("Feito", { exact: true })).toBeVisible();
    expect(await page.locator("body").innerText()).not.toContain("Minuta");
    const og = await page.locator('meta[property="og:image"]').getAttribute("content");
    expect(og).toContain("/site/og-1200.webp");
    for (const asset of ["/favicon.svg", "/favicon.ico", "/apple-touch-icon.png", "/brand/docfeito-logo.svg", "/brand/png/docfeito-icone-app-512.png"]) {
      expect((await page.request.get(asset)).ok(), asset).toBe(true);
    }
  });

  test("páginas legais existem", async ({ page }) => {
    for (const [path, title] of [["/termos", "Termos de uso"], ["/privacidade", "Política de privacidade"]] as const) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(title);
    }
  });
});
