import { describe, expect, it } from "vitest";
import vectors from "../../../../shared/field-vectors.json";
import { displayFor, detectType, liveMask } from "@/lib/fields/masks";
import { formatValue, isValidCnpj, isValidCpf, normalizeValue, quantize, validateRow, type FieldSpec } from "@/lib/fields/normalize";

type Case = { type: string; input: unknown; canonical: unknown; formatted: string | null; error: string | null; options?: { label: string; value: string }[]; config?: Record<string, unknown>; required?: boolean };

const spec = (c: Case): FieldSpec => ({ name: "campo", label: "Campo", type: c.type as FieldSpec["type"], required: !!c.required, options: c.options ?? [], config: c.config ?? {} });

describe("vetores compartilhados com o backend (Python)", () => {
  for (const c of vectors.cases as Case[]) {
    it(`${c.type}: ${JSON.stringify(c.input)}`, () => {
      const fd = spec(c);
      const { value, error } = normalizeValue(fd, c.input);
      expect(error).toBe(c.error);
      expect(value).toEqual(c.canonical);
      if (c.error === null) expect(formatValue(fd, value)).toBe(c.formatted);
    });
  }
});

describe("CPF/CNPJ", () => {
  it("valida CPF", () => {
    expect(isValidCpf("123.456.789-09")).toBe(true);
    expect(isValidCpf("111.111.111-11")).toBe(false);
  });
  it("valida CNPJ numérico e alfanumérico", () => {
    expect(isValidCnpj("11.222.333/0001-81")).toBe(true);
    expect(isValidCnpj("12ABC34501DE35")).toBe(true);
    expect(isValidCnpj("12ABC34501DE36")).toBe(false);
  });
});

describe("arredondamento half-even (igual ao Decimal do Python)", () => {
  it.each([["2.675", 2, "2.68"], ["2.665", 2, "2.66"], ["0.5", 0, "0"], ["1.5", 0, "2"], ["3.14159", 2, "3.14"], ["-0.004", 2, "0.00"], ["999.995", 2, "1000.00"]])(
    "quantize(%s, %i) = %s", (v, d, exp) => expect(quantize(v as string, d as number)).toBe(exp),
  );
});

describe("máscaras", () => {
  it("aplica máscara progressiva", () => {
    expect(liveMask("cpf", "52998224725")).toBe("529.982.247-25");
    expect(liveMask("cpf", "5299")).toBe("529.9");
    expect(liveMask("cnpj", "11222333000181")).toBe("11.222.333/0001-81");
    expect(liveMask("cep", "01310100")).toBe("01310-100");
    expect(liveMask("phone", "11912345678")).toBe("(11) 91234-5678");
    expect(liveMask("phone", "1131234567")).toBe("(11) 3123-4567");
    expect(liveMask("date", "21092026")).toBe("21/09/2026");
  });
  it("normaliza a exibição definitiva na grade", () => {
    const cur: FieldSpec = { name: "v", label: "V", type: "currency", required: false, options: [], config: {} };
    expect(displayFor(cur, "5000")).toBe("5.000,00");
    expect(displayFor(cur, "1234,5")).toBe("1.234,50");
    expect(displayFor({ ...cur, type: "date" }, "2026-09-21")).toBe("21/09/2026");
    expect(displayFor({ ...cur, type: "yes_no" }, "sim")).toBe("Sim");
    expect(displayFor({ ...cur, type: "cpf" }, "52998224725")).toBe("529.982.247-25");
  });
  it("detecta tipo da seleção", () => {
    expect(detectType("123.456.789-09")).toBe("cpf");
    expect(detectType("R$ 5.000,00")).toBe("currency");
    expect(detectType("01/10/2026")).toBe("date");
    expect(detectType("João da Silva")).toBe("text_short");
  });
});

describe("validateRow", () => {
  it("aplica padrão e reporta erros por campo", () => {
    const specs: FieldSpec[] = [
      { name: "nome", label: "Nome", type: "text_short", required: true, options: [], config: {} },
      { name: "valor", label: "Valor", type: "currency", required: false, default_value: "100", options: [], config: {} },
    ];
    const r = validateRow(specs, { nome: "" });
    expect(r.errors).toEqual({ nome: "Campo obrigatório." });
    expect(r.values.valor).toBe("100.00");
  });
});
