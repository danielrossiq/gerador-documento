import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

// Landing pública (/): CTAs, menu mobile, FAQ, axe WCAG 2.2 AA e ausência de rolagem lateral nas 4 larguras da spec.
// Capturas: LANDING_SHOTS=<pasta> grava uma página inteira por largura.
const WIDTHS = [1440, 1024, 390, 320];
const FORBIDDEN = [/pre[çc]o/i, /LGPD/, /intelig[êe]ncia artificial|\bIA\b/, /importa[çc][ãa]o de PDF/i, /aconselhamento/i];

test("visitante vê a landing com CTAs para entrar e criar conta", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Do seu modelo ao documento pronto para revisar.");
  await expect(page.getByRole("banner").getByRole("link", { name: "Entrar" })).toHaveAttribute("href", "/login");
  await expect(page.getByRole("banner").getByRole("link", { name: "Criar conta" })).toHaveAttribute("href", "/register");
  const text = await page.locator("main").innerText();
  for (const re of FORBIDDEN) expect(text, `copy não pode conter ${re}`).not.toMatch(re);

  await page.getByRole("banner").getByRole("link", { name: "Entrar" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/");
  await page.getByRole("main").getByRole("link", { name: "Criar conta" }).first().click();
  await expect(page).toHaveURL(/\/register$/);
});

test("FAQ abre por teclado e âncora leva a Como funciona", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Ver como funciona" }).click();
  await expect(page).toHaveURL(/#como-funciona$/);
  const summary = page.locator("summary", { hasText: "O que preciso para começar?" });
  await summary.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Um modelo .docx que você usa no escritório.")).toBeVisible();
});

test("usuário autenticado acessa / sem loop e segue para o painel", async ({ page }) => {
  await login(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Do seu modelo ao documento pronto para revisar.");
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/dashboard$/);
});

for (const width of WIDTHS) {
  test(`landing em ${width}px: sem rolagem lateral e sem violações axe`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    if (width < 1024) {
      const menu = page.getByRole("button", { name: "Abrir menu" });
      await expect(menu).toHaveAttribute("aria-expanded", "false");
      await menu.click();
      await expect(page.getByRole("button", { name: "Fechar menu" })).toHaveAttribute("aria-expanded", "true");
      await expect(page.getByRole("navigation", { name: "Menu de seções" }).getByRole("link", { name: "Recursos" })).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(page.getByRole("button", { name: "Abrir menu" })).toBeFocused();
    }
    await expect(page.getByRole("banner").getByRole("link", { name: "Criar conta" })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, "rolagem lateral").toBeLessThanOrEqual(0);
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
    expect(results.violations.map((v) => `${v.id}: ${v.nodes[0]?.html.slice(0, 120)}`)).toEqual([]);
    if (process.env.LANDING_SHOTS) {
      // carrega imagens lazy antes da captura de página inteira
      await page.evaluate(async () => {
        for (let y = 0; y < document.body.scrollHeight; y += 600) {
          window.scrollTo(0, y);
          await new Promise((r) => setTimeout(r, 60));
        }
        window.scrollTo(0, 0);
      });
      await page.waitForLoadState("networkidle");
      await page.screenshot({ path: `${process.env.LANDING_SHOTS}/landing-${width}.png`, fullPage: true });
    }
  });
}
