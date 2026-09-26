import { describe, expect, it } from "vitest";
import { previewFilename, unknownTokens } from "@/lib/fields/filename";
import { documentOrder, fieldIssues, isDocumentOrder, issuesByField, normalizeLabel, occurrenceCounts, sameLabelFields, sortByDocument } from "@/lib/fields/issues";
import { exampleValue, exampleValues, originalSamples } from "@/lib/fields/samples";
import type { DocNode, FieldOut, FieldType } from "@/lib/types";

function field(id: string, label: string, type: FieldType = "text_short", extra: Partial<FieldOut> = {}): FieldOut {
  return {
    id, name: id, label, type, description: null, required: false, default_value: null, example: null, mask: null, group_name: null,
    position: 0, include_in_batch: true, config: {}, options: [], occurrences: 0, missing_in_document: false, ...extra,
  };
}

const chip = (fieldId: string, sample = ""): DocNode => ({ type: "field", attrs: { fieldId, sample } });
const doc: DocNode = {
  type: "doc",
  content: [
    { type: "docPart", attrs: { kind: "header" }, content: [{ type: "paragraph", content: [chip("c", "ACME Ltda.")] }] },
    {
      type: "docPart",
      attrs: { kind: "body" },
      content: [
        { type: "paragraph", content: [{ type: "text", text: "Contratante: " }, chip("a", "João da Silva"), { type: "text", text: ", CPF " }, chip("b", "123.456.789-09")] },
        { type: "paragraph", content: [chip("a", "João da Silva")] },
      ],
    },
  ],
};

describe("pendências dos campos", () => {
  it("normaliza rótulos para comparar (acentos, maiúsculas, espaços)", () => {
    expect(normalizeLabel("  Data de  Início ")).toBe("data de inicio");
    expect(sameLabelFields([field("x", "Data"), field("y", "data "), field("z", "Valor")], "DATA", "x").map((f) => f.id)).toEqual(["y"]);
  });

  it("aponta nomes repetidos, listas sem opção e campos fora do documento", () => {
    const fields = [field("a", "Data"), field("b", "data"), field("c", "Serviço", "select"), field("d", "Valor", "currency")];
    const issues = issuesByField(fieldIssues(fields, { a: 1, b: 2, c: 1 }));
    expect(issues.a.map((i) => i.kind)).toEqual(["duplicate_label"]);
    expect(issues.b.map((i) => i.kind)).toEqual(["duplicate_label"]);
    expect(issues.c.map((i) => i.kind)).toEqual(["empty_options"]);
    expect(issues.c[0].severity).toBe("error");
    expect(issues.d.map((i) => i.kind)).toEqual(["not_in_document"]);
  });

  it("lista com opções em branco continua sendo lista vazia; sem contagem não acusa 'fora do documento'", () => {
    const f = field("s", "Serviço", "select", { options: [{ label: " ", value: "x" }] });
    expect(fieldIssues([f]).map((i) => i.kind)).toEqual(["empty_options"]);
    const ok = field("s", "Serviço", "select", { options: [{ label: "Suporte", value: "suporte" }] });
    expect(fieldIssues([ok])).toEqual([]);
  });
});

describe("ordem do documento", () => {
  it("segue a primeira aparição (cabeçalho antes do corpo) e conta ocorrências", () => {
    expect(documentOrder(doc)).toEqual(["c", "a", "b"]);
    expect(occurrenceCounts(doc)).toEqual({ c: 1, a: 2, b: 1 });
  });

  it("ordena pelo documento e deixa quem não aparece no fim, na ordem atual", () => {
    const fields = [field("z", "Fora 1"), field("b", "CPF"), field("y", "Fora 2"), field("a", "Nome"), field("c", "Empresa")];
    expect(sortByDocument(fields, documentOrder(doc)).map((f) => f.id)).toEqual(["c", "a", "b", "z", "y"]);
    expect(isDocumentOrder(fields, documentOrder(doc))).toBe(false);
    expect(isDocumentOrder([field("c", "1"), field("a", "2"), field("b", "3"), field("z", "4")], documentOrder(doc))).toBe(true);
  });
});

describe("valores de exemplo", () => {
  it("usa o trecho original do documento quando ele é válido", () => {
    expect(originalSamples(doc)).toEqual({ c: "ACME Ltda.", a: "João da Silva", b: "123.456.789-09" });
    const vals = exampleValues([field("a", "Nome"), field("b", "CPF", "cpf")], doc);
    expect(vals).toEqual({ a: "João da Silva", b: "123.456.789-09" });
  });

  it("prefere o exemplo configurado e cai para um valor genérico válido", () => {
    expect(exampleValue(field("v", "Valor", "currency", { example: "R$ 2.500,00" }))).toBe("2.500,00");
    expect(exampleValue(field("c", "CPF", "cpf"), "000.000.000-00")).toBe("529.982.247-25"); // original inválido é ignorado
    expect(exampleValue(field("d", "Data", "date"), "01/10/2026")).toBe("2026-10-01");
    expect(exampleValue(field("q", "Renovação", "yes_no"))).toBe("Sim");
    expect(exampleValue(field("k", "Aceite", "checkbox"))).toBe(true);
  });

  it("lista de opções: usa uma opção existente; sem opções não inventa valor", () => {
    const opts = [{ label: "Suporte", value: "suporte" }, { label: "Treinamento", value: "treinamento" }];
    expect(exampleValue(field("s", "Serviço", "select", { options: opts }), "Treinamento")).toBe("treinamento");
    expect(exampleValue(field("s", "Serviço", "select", { options: opts }))).toBe("suporte");
    expect(exampleValue(field("s", "Serviço", "select"))).toBeNull();
  });
});

describe("nome do arquivo", () => {
  it("monta o nome com os valores e aponta códigos desconhecidos", () => {
    const fields = [field("nome", "Nome")];
    expect(previewFilename("Contrato_{nome}_{linha}", fields, { nome: "Ana Lima" }, "Contrato", 3)).toBe("Contrato_Ana_Lima_0003");
    expect(previewFilename("{nome}", fields, {}, "Contrato")).toBe("documento");
    expect(unknownTokens("Contrato_{nome}_{cpf}_{hoje}", fields)).toEqual(["cpf"]);
  });
});
