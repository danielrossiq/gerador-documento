import { expect, type Download, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

export const DEMO = { email: "demo@docfeito.com.br", password: "demo12345" };
export const DEMO_DIR = path.resolve(__dirname, "..", "..", "demo");
export const DOCX = path.join(DEMO_DIR, "contrato_prestacao_servicos.docx");
export const XLSX = path.join(DEMO_DIR, "lote_exemplo.xlsx");

export async function login(page: Page, email = DEMO.email, password = DEMO.password) {
  await page.goto("/login");
  await page.getByLabel(/^E-mail/).fill(email);
  await page.getByLabel(/^Senha/).fill(password);
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.waitForURL("**/dashboard");
}

export async function register(page: Page, email: string, password = "senha-forte-123") {
  await page.goto("/register");
  await page.locator('input[autocomplete="name"]').fill("Pessoa E2E");
  await page.getByLabel(/^E-mail/).fill(email);
  await page.getByLabel(/^Senha/).first().fill(password);
  await page.getByLabel(/^Confirmar senha/).fill(password);
  await page.getByLabel(/Nome do espaço de trabalho/).fill("Empresa E2E");
  await page.getByRole("button", { name: "Criar conta" }).click();
  await page.waitForURL("**/dashboard");
}

export async function demoGeneratorId(page: Page): Promise<string> {
  const r = await page.request.get("/api/v1/generators?q=Contrato%20de%20presta");
  const j = (await r.json()) as { items: { id: string; has_template: boolean }[] };
  const g = j.items.find((x) => x.has_template) ?? j.items[0];
  expect(g, "gerador de demonstração (rode o seed)").toBeTruthy();
  return g.id;
}

/** Lê o download em memória. */
export async function readDownload(d: Download): Promise<Buffer> {
  const p = await d.path();
  return fs.readFileSync(p!);
}

/** Cabeçalho CSRF exigido pelas mutações da API (cookie legível `minuta_csrf`; ver app/core/deps.py). */
export async function csrfHeaders(page: Page): Promise<Record<string, string>> {
  const cookies = await page.context().cookies();
  const c = cookies.find((x) => x.name === "minuta_csrf");
  return c ? { "X-CSRF-Token": c.value } : {};
}

/** Cria, via API (contorna o assistente do editor), um gerador já pronto para uso com os campos dados —
 * usado para montar rapidamente cenários que precisam de vários geradores prontos (ex.: kits). */
export async function createUsableGenerator(
  page: Page,
  name: string,
  fields: { label: string; type: string; required?: boolean; options?: { label: string }[] }[],
): Promise<string> {
  const headers = await csrfHeaders(page);
  const g = await page.request.post("/api/v1/generators", { data: { name }, headers });
  const gid = ((await g.json()) as { id: string }).id;
  await page.request.post(`/api/v1/generators/${gid}/template`, {
    headers,
    multipart: {
      file: {
        name: "modelo.docx",
        mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        buffer: fs.readFileSync(DOCX),
      },
    },
  });
  for (const f of fields) {
    await page.request.post(`/api/v1/generators/${gid}/fields`, { data: f, headers });
  }
  return gid;
}

/** Espera o indicador de salvamento do editor chegar em "Salvo". */
export async function waitSaved(page: Page) {
  await expect(page.getByTestId("save-state")).toHaveAttribute("data-state", "saved", { timeout: 20_000 });
}

/** Seleciona um trecho de texto dentro de um parágrafo do editor (por DOM Range) e devolve o texto selecionado. */
export async function selectText(page: Page, blockKey: string, needle: string, occurrence = 0) {
  const p = page.locator(`.doc-page p[data-block-key="${blockKey}"]`).first();
  await p.click({ position: { x: 4, y: 4 } }); // foca o editor
  await p.evaluate(
    (el, { needle, occurrence }) => {
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      let seen = 0;
      let node: Node | null;
      while ((node = walker.nextNode())) {
        const text = node.textContent ?? "";
        let i = text.indexOf(needle);
        while (i >= 0) {
          if (seen === occurrence) {
            const range = document.createRange();
            range.setStart(node, i);
            range.setEnd(node, i + needle.length);
            const sel = window.getSelection()!;
            sel.removeAllRanges();
            sel.addRange(range);
            return;
          }
          seen++;
          i = text.indexOf(needle, i + needle.length);
        }
      }
      throw new Error(`Trecho não encontrado: ${needle}`);
    },
    { needle, occurrence },
  );
}
