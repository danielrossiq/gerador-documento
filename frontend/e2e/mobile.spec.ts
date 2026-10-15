import { expect, test, type Page } from "@playwright/test";
import path from "node:path";
import { login } from "./helpers";

// Celular (390 px): a home, a lista de modelos e a colagem de planilha não rolam na horizontal e mantêm
// as ações principais ao alcance.
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

async function noHorizontalScroll(page: Page, name: string) {
  const over = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
    wide: [...document.querySelectorAll("body *")]
      .filter((e) => e.getBoundingClientRect().right > document.documentElement.clientWidth + 1 && !e.closest(".overflow-x-auto"))
      .slice(0, 4)
      .map((e) => `${e.tagName.toLowerCase()}.${String(e.className).slice(0, 50)}`),
  }));
  expect(over.scroll, `rolagem horizontal em ${name}: ${over.wide.join(" | ")}`).toBeLessThanOrEqual(over.client);
}

test("home e modelos no celular: sem rolagem horizontal e com as ações principais", async ({ page }) => {
  await login(page);
  await expect(page.getByTestId("home-new-model")).toBeVisible();
  await expect(page.getByTestId("home-paste")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Principal" })).toBeVisible();
  await noHorizontalScroll(page, "início");
  if (process.env.CAPTURE_SCREENSHOTS) {
    await page.screenshot({ path: path.resolve(__dirname, "..", "..", "docs", "screenshots", "19-inicio-celular-390.png") });
  }

  const area = page.getByTestId("paste-area");
  await area.fill("Nome do contratante\tCPF do contratante\nMaria Souza\t529.982.247-25\nJoão Lima\t111.444.777-35");
  await expect(page.getByTestId("paste-result")).toBeVisible();
  await expect(page.getByTestId("paste-go")).toBeVisible();
  await noHorizontalScroll(page, "colar planilha");

  await page.goto("/models");
  await expect(page.getByRole("heading", { name: "Modelos", level: 1 })).toBeVisible();
  await expect(page.getByTestId("generator-card").first()).toBeVisible();
  await noHorizontalScroll(page, "modelos");

  await page.goto("/generators/new");
  await expect(page.getByTestId("docx-input")).toBeAttached();
  await noHorizontalScroll(page, "novo modelo");
});
