import { devices, expect, test } from "@playwright/test";

// LCP e CLS da landing no celular (landing-spec-v2 §8/§12: LCP ≤ 2,5 s, CLS ≤ 0,05; acima da dobra ≤ 150 KB de
// imagem). Opt-in: LANDING_PERF=1. Medido contra a stack local, sem throttling de rede.
test.skip(!process.env.LANDING_PERF, "defina LANDING_PERF=1");
test.use({ ...devices["Pixel 7"], viewport: { width: 390, height: 844 } });

test("landing no celular: LCP, CLS e peso das imagens acima da dobra", async ({ page }) => {
  const images: { url: string; bytes: number }[] = [];
  page.on("response", async (r) => {
    if (r.request().resourceType() === "image" && r.url().includes("/site/")) {
      images.push({ url: r.url(), bytes: Number(r.headers()["content-length"] ?? (await r.body()).length) });
    }
  });
  await page.addInitScript(() => {
    const w = window as unknown as { __lcp: number; __cls: number };
    w.__lcp = 0;
    w.__cls = 0;
    new PerformanceObserver((l) => l.getEntries().forEach((e) => (w.__lcp = e.startTime))).observe({ type: "largest-contentful-paint", buffered: true });
    new PerformanceObserver((l) =>
      l.getEntries().forEach((e) => {
        const s = e as PerformanceEntry & { value: number; hadRecentInput: boolean };
        if (!s.hadRecentInput) w.__cls += s.value;
      }),
    ).observe({ type: "layout-shift", buffered: true });
  });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  const { lcp, cls } = await page.evaluate(() => {
    const w = window as unknown as { __lcp: number; __cls: number };
    return { lcp: w.__lcp, cls: w.__cls };
  });
  const above = images.reduce((s, i) => s + i.bytes, 0);
  console.log(`LCP ${Math.round(lcp)} ms · CLS ${cls.toFixed(3)} · imagens /site/ carregadas sem rolar: ${Math.round(above / 1024)} KB`, images.map((i) => i.url.split("/").pop()));
  expect(lcp).toBeLessThanOrEqual(2500);
  expect(cls).toBeLessThanOrEqual(0.05);
  expect(above).toBeLessThanOrEqual(150 * 1024);
});
