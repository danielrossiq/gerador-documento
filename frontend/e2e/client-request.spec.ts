import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { demoGeneratorId, login } from "./helpers";

// Link para o cliente preencher (D39): o profissional pede, o cliente responde pelo celular, a resposta volta para a
// tela Gerar já no formulário. Precisa do seed (conta demo com o contrato de exemplo).

type PublicField = { name: string; type: string; options: { value: string }[] };

async function fillLikeAClient(page: Page, fields: PublicField[]) {
  for (const f of fields) {
    const el = page.getByTestId(`field-${f.name}`);
    if (f.type === "cpf") await el.fill("529.982.247-25");
    else if (f.type === "date") await el.fill("2026-11-10");
    else if (f.type === "currency") await el.fill("1.500,00");
    else if (f.type === "select") await el.selectOption(f.options[0].value);
    else if (f.type === "yes_no") await page.getByTestId(`field-${f.name}-Sim`).check();
    else if (f.type === "checkbox") await el.check();
    else await el.fill("Ana Lima Prado");
  }
}

test.describe("link para o cliente preencher", () => {
  test("o cliente preenche pelo celular e a resposta volta para o formulário de quem pediu", async ({ page, browser }) => {
    await login(page);
    const gid = await demoGeneratorId(page);
    await page.goto(`/generators/${gid}/use`);
    await page.getByTestId("ask-client").click();
    await page.getByLabel(/Mensagem para o cliente/).fill("Oi! Preencha seus dados <b>para o contrato</b>.");
    await page.getByTestId("request-create").click();
    const url = await page.getByTestId("request-url").inputValue();
    expect(url).toMatch(/\/r\/[A-Za-z0-9_-]{40,64}$/);
    await expect(page.getByTestId("request-whatsapp")).toHaveAttribute("href", /^https:\/\/wa\.me\/\?text=/);
    await page.getByRole("button", { name: "Concluir" }).click();
    const token = url.split("/r/")[1];

    // o cliente, num celular, sem conta
    const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, locale: "pt-BR" });
    const client = await phone.newPage();
    const res = await client.goto(`/r/${token}`);
    expect(res?.headers()["content-security-policy"] ?? "").toContain("'strict-dynamic'");
    await expect(client.getByRole("heading", { level: 1 })).toContainText("Contrato de prestação de serviços");
    // a mensagem do profissional aparece como texto (escapada), nunca como HTML
    await expect(client.getByTestId("request-note")).toHaveText("Oi! Preencha seus dados <b>para o contrato</b>.");
    const info = (await (await client.request.get(`/api/v1/public/requests/${token}`)).json()) as { fields: PublicField[] };
    const cpf = info.fields.find((f) => f.type === "cpf");
    if (cpf) {
      await client.getByTestId(`field-${cpf.name}`).fill("111.111.111-11");
      await client.getByTestId("request-submit").click();
      await expect(client.getByText(/CPF inválido/).first()).toBeVisible();
    }
    await fillLikeAClient(client, info.fields);
    await client.getByTestId("request-submit").click();
    await expect(client.getByTestId("request-message")).toContainText("recebemos seus dados");
    const overflow = await client.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    const axe = await new AxeBuilder({ page: client }).withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(axe.violations.map((v) => v.id)).toEqual([]);

    // de volta ao profissional: aviso no menu e "Respostas recebidas" no Início
    await page.goto("/dashboard");
    await expect(page.getByTestId("answers-badge")).toBeVisible({ timeout: 60_000 });
    const row = page.getByTestId("request-row").filter({ hasText: "Respondido" }).first();
    await row.getByTestId("request-open").click();
    await page.waitForURL(/\/use\?request=/);
    await expect(page.getByText(/Dados enviados pelo cliente/)).toBeVisible();
    if (cpf) await expect(page.getByTestId(`field-${cpf.name}`)).toHaveValue("529.982.247-25");

    // depois de aberta, o cliente não altera mais
    await client.reload();
    await expect(client.getByTestId("request-message")).toContainText("já foram recebidos");
    await phone.close();
  });

  test("link cancelado ou inexistente mostra um aviso, sem dados", async ({ page }) => {
    await page.goto(`/r/${"x".repeat(43)}`);
    await expect(page.getByTestId("request-message")).toContainText("não está mais disponível");
  });
});
