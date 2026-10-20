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
    const media: string[] = [];
    page.on("request", (r) => /\.(mp4|webm)(\?|$)/.test(r.url()) && media.push(r.url()));
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
      await expect(page.getByRole("navigation", { name: "Seções da página" })).toBeHidden();
    } else {
      // âncoras completas visíveis: o botão do menu agrupado não aparece
      await expect(page.getByRole("navigation", { name: "Seções da página" }).getByRole("link", { name: "Recursos" })).toBeVisible();
      await expect(page.locator(".lp-menu-btn")).toBeHidden();
    }
    await expect(page.getByRole("banner").getByRole("link", { name: "Criar conta" })).toBeVisible();
    // P0 da v2: nada no cabeçalho quebra em duas linhas (marca, links e botões)
    const wrapped = await page.locator(".lp-header-row").evaluate((row) =>
      [...row.querySelectorAll<HTMLElement>(".lp-brand, a, button")]
        .filter((el) => el.offsetParent !== null)
        .filter((el) => {
          // só os nós de texto: a lacuna decorativa da marca (::after) não conta como linha
          const tops = new Set<number>();
          const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
          for (let n = walker.nextNode(); n; n = walker.nextNode()) {
            if (!n.textContent?.trim()) continue;
            const r = document.createRange();
            r.selectNodeContents(n);
            for (const rect of r.getClientRects()) tops.add(Math.round(rect.top));
          }
          return tops.size > 1;
        })
        .map((el) => el.textContent?.trim()),
    );
    expect(wrapped, "itens do cabeçalho partidos").toEqual([]);
    if (width < 380) {
      await expect(page.getByRole("banner").getByRole("link", { name: "Entrar" }).first()).toBeHidden();
      await page.getByRole("button", { name: "Abrir menu" }).click();
      await expect(page.getByRole("navigation", { name: "Menu de seções" }).getByRole("link", { name: "Entrar" })).toBeVisible();
      await page.keyboard.press("Escape");
    }
    // seção nova com capturas reais; mídia gerada ausente: nenhum vídeo e nenhuma caixa vazia no hero
    await expect(page.getByRole("heading", { name: "Como fica na tela." })).toBeVisible();
    const shots = page.locator("#como-fica-na-tela figure:visible img");
    expect(await shots.count()).toBe(2);
    for (const img of await shots.all()) expect((await img.getAttribute("alt"))?.length).toBeGreaterThan(20);
    await expect(page.getByRole("main").getByRole("link", { name: "Entrar" })).toHaveAttribute("href", "/login");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, "rolagem lateral").toBeLessThanOrEqual(0);
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
    expect(results.violations.map((v) => `${v.id}: ${v.nodes[0]?.html.slice(0, 120)}`)).toEqual([]);
    if (width < 768) expect(media, "vídeo baixado abaixo de 768 px").toEqual([]);
    if (process.env.LANDING_SHOTS) {
      // carrega imagens lazy antes da captura de página inteira
      await page.evaluate(async () => {
        // "instant": a landing usa scroll-behavior smooth, e a captura sairia no meio da rolagem
        for (let y = 0; y < document.body.scrollHeight; y += 600) {
          window.scrollTo({ top: y, behavior: "instant" });
          await new Promise((r) => setTimeout(r, 60));
        }
        window.scrollTo({ top: 0, behavior: "instant" });
        (document.activeElement as HTMLElement | null)?.blur();
      });
      await page.waitForLoadState("networkidle");
      await page.screenshot({ path: `${process.env.LANDING_SHOTS}/landing-${width}.png`, fullPage: true });
    }
  });
}
