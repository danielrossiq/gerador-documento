import { expect, test } from "@playwright/test";
import path from "node:path";

// Captura só da seção "Como fica na tela" (revisão do Design). Opt-in: LANDING_SHOTS=<pasta>.
const OUT = process.env.LANDING_SHOTS;
test.skip(!OUT, "defina LANDING_SHOTS=<pasta>");

for (const width of [1440, 1024]) {
  test(`seção Como fica na tela em ${width}px, lado a lado e sem sobreposição`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/#como-fica-na-tela");
    const section = page.locator("#como-fica-na-tela");
    const editor = section.locator(".lp-shot-desktop img");
    const phone = section.locator(".lp-shot-form-mobile img");
    await expect(editor).toBeVisible();
    await page.waitForLoadState("networkidle");
    const a = (await editor.boundingBox())!;
    const b = (await phone.boundingBox())!;
    expect(a.x + a.width, "celular sobre o editor").toBeLessThanOrEqual(b.x);
    await section.screenshot({ path: path.join(OUT!, `secao-tela-${width}.png`) });
  });
}
