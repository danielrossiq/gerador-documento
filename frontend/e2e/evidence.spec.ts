import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { demoGeneratorId, login } from "./helpers";

// Coleta de evidências para a matriz de aceite da Fase 2 (design/fase2-minuta-especificacao.md):
// cada rota × viewport (1440, 1024, 390, 320) → captura full-page, rolagem horizontal da página e axe com
// WCAG 2.0/2.1/2.2 A/AA. Sob demanda (EVIDENCE=1); NÃO falha por violação — registra tudo em
// docs/evidence/fase2/resultados.json para a revisão de design. Automação não substitui teste manual.
test.skip(!process.env.EVIDENCE, "somente sob demanda (EVIDENCE=1)");
test.setTimeout(600_000);

const OUT = path.resolve(__dirname, "..", "..", "docs", "evidence", "fase2");
const VIEWPORTS = [
  { name: "1440", width: 1440, height: 900 },
  { name: "1024", width: 1024, height: 768 },
  { name: "390", width: 390, height: 844 },
  { name: "320", width: 320, height: 720 },
];

type Row = {
  id: string;
  route: string;
  state: string;
  viewport: string;
  screenshot: string;
  pageScrollWidth: number;
  clientWidth: number;
  horizontalOverflow: boolean;
  overflowingElements: string[];
  axe: { id: string; impact: string | null | undefined; nodes: number; example: string }[];
};

const rows: Row[] = [];

async function record(page: Page, id: string, route: string, state: string, vp: string) {
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await page.waitForTimeout(400);
  const file = `${vp}/${id}.png`;
  fs.mkdirSync(path.join(OUT, vp), { recursive: true });
  await page.screenshot({ path: path.join(OUT, file), fullPage: true });
  const m = await page.evaluate(() => {
    const cw = document.documentElement.clientWidth;
    const wide = [...document.querySelectorAll("body *")]
      .filter((e) => {
        const r = e.getBoundingClientRect();
        return r.width > 0 && r.right > cw + 1 && !e.closest('[role="region"], .overflow-x-auto, .overflow-auto');
      })
      .slice(0, 5)
      .map((e) => `${e.tagName.toLowerCase()}${e.id ? "#" + e.id : ""}.${String(e.className).split(" ").slice(0, 3).join(".")}`);
    return { sw: document.documentElement.scrollWidth, cw, wide };
  });
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  rows.push({
    id,
    route,
    state,
    viewport: vp,
    screenshot: file,
    pageScrollWidth: m.sw,
    clientWidth: m.cw,
    horizontalOverflow: m.sw > m.cw,
    overflowingElements: m.wide,
    axe: axe.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, example: v.nodes[0]?.html.slice(0, 160) ?? "" })),
  });
}

for (const vp of VIEWPORTS) {
  test(`evidências ${vp.name}px`, async ({ page, request, browser }) => {
    await page.setViewportSize({ width: vp.width, height: vp.height });

    // ---- sem sessão
    await page.goto("/login");
    await record(page, "A1-login", "/login", "inicial", vp.name);
    await page.getByRole("button", { name: "Entrar" }).click();
    await record(page, "A1-login-erro", "/login", "erro de campo (vazio)", vp.name);
    await page.goto("/register");
    await record(page, "A2-cadastro", "/register", "inicial", vp.name);
    await page.goto("/forgot-password");
    await record(page, "A3-esqueci-senha", "/forgot-password", "inicial", vp.name);
    await page.goto("/reset-password");
    await record(page, "A4-redefinir-sem-token", "/reset-password", "link inválido (sem token)", vp.name);
    await page.goto("/reset-password?token=token-invalido-de-teste");
    await record(page, "A4-redefinir-token", "/reset-password?token=…", "formulário com token (validação no envio)", vp.name);

    // ---- com sessão (conta de demonstração, dados fictícios)
    await login(page);
    await record(page, "M1-inicio", "/dashboard", "preenchido", vp.name);
    await page.goto("/models");
    await record(page, "M1b-modelos", "/models", "lista", vp.name);
    await page.goto("/generators/new");
    await record(page, "M2-novo-modelo", "/generators/new", "inicial", vp.name);
    const gid = await demoGeneratorId(page);
    for (const [id, step, state] of [
      ["M2b-documento", "template", "documento enviado"],
      ["M3-editor", "edit", "pronto"],
      ["M3b-revisao", "review", "dados de exemplo"],
      ["M4-preencher", "use", "formulário"],
      ["M5-lote", "batch", "grade"],
    ] as const) {
      await page.goto(`/generators/${gid}/${step}`);
      await record(page, id, `/generators/[id]/${step}`, state, vp.name);
    }
    await page.goto(`/generators/${gid}/use`);
    await page.getByTestId("generate-docx").click();
    await record(page, "M4-preencher-erro", "/generators/[id]/use", "erros de validação ao gerar vazio", vp.name);

    await page.goto("/kits");
    await record(page, "M6-kits", "/kits", "lista ou vazio", vp.name);
    await page.goto("/kits/new");
    await record(page, "M7-novo-kit", "/kits/new", "inicial", vp.name);
    const kits = (await (await page.request.get("/api/v1/kits")).json()) as { items: { id: string }[] };
    if (kits.items[0]) {
      await page.goto(`/kits/${kits.items[0].id}/edit`);
      await record(page, "M8-kit-editar", "/kits/[id]/edit", "mapeamento", vp.name);
      await page.goto(`/kits/${kits.items[0].id}/use`);
      await record(page, "M9-kit-usar", "/kits/[id]/use", "formulário", vp.name);
    }
    await page.goto("/history");
    await record(page, "M10-historico", "/history", "lista", vp.name);
    const jobs = (await (await page.request.get("/api/v1/jobs")).json()) as { items: { id: string; status: string }[] };
    for (const status of ["succeeded", "partial", "failed"]) {
      const j = jobs.items.find((x) => x.status === status);
      if (!j) continue;
      await page.goto(`/history/${j.id}`);
      await record(page, `M11-historico-${status}`, "/history/[id]", status, vp.name);
    }
    void request;
    void browser;
  });
}

test.afterAll(() => {
  fs.mkdirSync(OUT, { recursive: true });
  const file = path.join(OUT, "resultados.json");
  const previous: Row[] = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf-8")) : [];
  const key = (r: Row) => `${r.viewport}/${r.id}`;
  const merged = new Map(previous.map((r) => [key(r), r]));
  for (const r of rows) merged.set(key(r), r);
  fs.writeFileSync(file, JSON.stringify([...merged.values()], null, 1));
  expect(rows.length).toBeGreaterThan(0);
});
