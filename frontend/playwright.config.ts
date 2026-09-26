import { defineConfig, devices } from "@playwright/test";

// E2E contra uma stack já em execução (docker compose up) ou o modo local. Configure:
//   E2E_BASE_URL=http://localhost:3000   E2E_CHANNEL=msedge (usa o Edge instalado; omita para o Chromium do Playwright)
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: {
    baseURL,
    locale: "pt-BR",
    acceptDownloads: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    channel: process.env.E2E_CHANNEL || undefined,
    viewport: { width: 1440, height: 900 },
    permissions: ["clipboard-read", "clipboard-write"],
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
});
