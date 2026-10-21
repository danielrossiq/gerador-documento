import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// Comportamento do vídeo do hero (landing-spec-v2 §8) e evidências do §12. Só roda quando o vídeo existe no build.
// Capturas: LANDING_SHOTS=<pasta>.
const OUT = process.env.LANDING_SHOTS;
const media = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "src/components/landing/site-media.json"), "utf8"));
test.skip(!media.videos?.["hero-loop"], "sem vídeo do hero no build");

function trackVideo(page: Page) {
  const urls: string[] = [];
  page.on("request", (r) => /\.(mp4|webm)(\?|$)/.test(r.url()) && urls.push(r.url().split("/").pop()!));
  return urls;
}

test("1440: vídeo entra depois do load, mudo e em loop, com botão de pausar que respeita a escolha", async ({ page }) => {
  const urls = trackVideo(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const stage = page.locator(".lp-stage");
  await expect(stage).toHaveAttribute("data-video", "on", { timeout: 10_000 });
  await expect(stage).toHaveAttribute("data-ready", "true", { timeout: 15_000 });
  const v = stage.locator("video");
  expect(await v.evaluate((el: HTMLVideoElement) => ({ muted: el.muted, loop: el.loop, paused: el.paused }))).toEqual({ muted: true, loop: true, paused: false });
  expect(urls.length).toBeGreaterThan(0);
  const btn = page.getByRole("button", { name: "Pausar animação" });
  await btn.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Reproduzir animação" })).toBeFocused();
  expect(await v.evaluate((el: HTMLVideoElement) => el.paused)).toBe(true);
  if (OUT) await page.screenshot({ path: path.join(OUT, "video-pausado-foco-1440.png") });
  await page.reload();
  await expect(page.getByRole("button", { name: "Reproduzir animação" })).toBeVisible(); // pausa lembrada na sessão
  await expect(stage).toHaveAttribute("data-video", "off");
  await page.getByRole("button", { name: "Reproduzir animação" }).click();
  await expect(stage).toHaveAttribute("data-ready", "true", { timeout: 15_000 });
  if (OUT) await page.screenshot({ path: path.join(OUT, "primeira-dobra-1440.png") });
});

for (const [name, width, motion] of [
  ["1440 com reduzir movimento", 1440, "reduce"],
  ["390", 390, "no-preference"],
] as const) {
  test(`${name}: nenhum vídeo baixado, pôster estático e sem botão`, async ({ page }) => {
    const urls = trackVideo(page);
    await page.emulateMedia({ reducedMotion: motion });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(3000); // passa do load + requestIdleCallback (timeout 2 s)
    expect(urls, "requisições .mp4/.webm").toEqual([]);
    await expect(page.locator(".lp-stage video")).toHaveCount(0);
    await expect(page.locator(".lp-stage-btn")).toHaveCount(0);
    if (OUT) {
      const tag = width === 390 ? "primeira-dobra-390" : "reduzir-movimento-1440";
      await page.screenshot({ path: path.join(OUT, `${tag}.png`) });
      fs.writeFileSync(path.join(OUT, `${tag}-rede.txt`), `requisições .mp4/.webm: ${urls.length}\n`);
    }
  });
}
