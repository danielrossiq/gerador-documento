import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { csrfHeaders, login } from "./helpers";

// Capturas reais do produto para a seção "Como fica na tela" da landing (landing-spec-v2 §9). Conta descartável com
// o contrato de exemplo sem imagem nem quebra de página (dados fictícios), sem sugestões pendentes; DPR 2, tema
// claro, só a viewport, sem foco, hover ou toast à vista. A conta de demonstração do seed não é alterada.
//   docker exec -i minuta-fase0-api-1 python - < scripts/capture_workspace.py   (imprime o e-mail)
//   SITE_CAPTURES=<pasta> SITE_CAPTURES_EMAIL=<e-mail> npx playwright test e2e/site-captures.spec.ts
//   python scripts/site_captures.py <pasta>
const OUT = process.env.SITE_CAPTURES;
test.skip(!OUT, "defina SITE_CAPTURES=<pasta> para gerar as capturas");
test.use({ deviceScaleFactor: 2, colorScheme: "light" });

// Conta criada por scripts/capture_workspace.py (contrato de exemplo sem imagem e sem quebra de página).
const EMAIL = process.env.SITE_CAPTURES_EMAIL;

async function prepare(page: Page): Promise<string> {
  expect(EMAIL, "rode scripts/capture_workspace.py e defina SITE_CAPTURES_EMAIL").toBeTruthy();
  await login(page, EMAIL, "senha-forte-123");
  const headers = await csrfHeaders(page);
  const list = (await (await page.request.get("/api/v1/generators?q=Contrato")).json()) as { items: { id: string }[] };
  expect(list.items, "contrato de captura").toHaveLength(1);
  const { id } = list.items[0];
  const pending = async () =>
    (await (await page.request.get(`/api/v1/generators/${id}/suggestions`)).json()) as {
      items: { id: string }[];
      analysis: { status: string };
    };
  await expect.poll(async () => (await pending()).analysis.status, { timeout: 90_000 }).toBe("done");
  for (const s of (await pending()).items) {
    const r = await page.request.post(`/api/v1/suggestions/${s.id}/ignore?apply_to_all=true`, { headers });
    expect(r.ok(), "ignorar sugestão").toBeTruthy();
  }
  expect((await pending()).items, "sugestões pendentes").toHaveLength(0);
  return id;
}

async function quiet(page: Page) {
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.mouse.move(-10, -10); // mouse fora da tela: nenhum hover
  await expect(page.locator('div.fixed[aria-live="polite"] > *'), "toast à vista").toHaveCount(0, { timeout: 12_000 });
  await page.evaluate(() => document.fonts.ready);
}

async function openEditor(page: Page, id: string) {
  await page.goto(`/generators/${id}/edit`);
  await expect(page.getByText("Tudo salvo")).toBeVisible();
  await expect(page.locator(".field-chip").first()).toBeVisible();
}

test("capturas C1, C1m e C2m", async ({ page }) => {
  fs.mkdirSync(OUT!, { recursive: true });
  const id = await prepare(page);

  // C1: editor no desktop, etapa Campos, aba Campos, sem sugestões pendentes, "Tudo salvo"
  await page.setViewportSize({ width: 1440, height: 900 });
  await openEditor(page, id);
  await page.getByRole("tab", { name: /^Campos/ }).click();
  await expect(page.getByRole("tab", { name: /^Campos/ })).toHaveAttribute("data-state", "active");
  await expect(page.getByRole("tab", { name: /Sugestões/ })).toHaveText("Sugestões");
  await quiet(page);
  await page.screenshot({ path: path.join(OUT!, "tela-editor-desktop.png") });

  // C1m: mesmo estado no celular, topo do documento com os campos (recorte de 390 × 640)
  await page.setViewportSize({ width: 390, height: 844 });
  await openEditor(page, id);
  await quiet(page);
  await page.screenshot({ path: path.join(OUT!, "tela-editor-mobile.png"), clip: { x: 0, y: 0, width: 390, height: 640 } });

  // C2m: "Um documento", aba Formulário, depois de "Preencher com dados de exemplo"
  await page.goto(`/generators/${id}/use`);
  const formTab = page.getByRole("tab", { name: "Formulário" });
  if (await formTab.isVisible()) await formTab.click();
  await page.getByTestId("fill-example").click();
  await expect(page.locator('input[data-testid^="field-"]').first()).not.toHaveValue("");
  // título do formulário no topo e 3 ou 4 campos preenchidos à vista (acima da barra fixa de ações)
  await page.evaluate(() => {
    const form = document.querySelector('form[aria-label="Formulário do documento"]');
    if (form) window.scrollTo(0, form.getBoundingClientRect().top + window.scrollY - 72);
  });
  await quiet(page);
  await page.screenshot({ path: path.join(OUT!, "tela-preencher-mobile.png") });
});
