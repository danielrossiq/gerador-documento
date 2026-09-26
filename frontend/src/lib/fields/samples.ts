// Valores de exemplo para a prévia da revisão, o botão "Preencher com exemplo" e a linha de exemplo do lote.
// Prioridade: exemplo configurado → valor padrão → o trecho original do documento → um valor genérico por tipo.
// Todo candidato passa pela mesma validação do formulário; um CPF de exemplo inválido nunca aparece como "certo".
import { normalizeValue, type FieldSpec } from "@/lib/fields/normalize";
import type { DocNode, FieldOut, FieldType } from "@/lib/types";

const GENERIC: Record<FieldType, string> = {
  text_short: "Maria Aparecida Souza",
  text_long: "Texto de exemplo com algumas linhas para ver como o parágrafo fica no documento.",
  number: "10",
  currency: "1.500,00",
  date: "", // preenchida com a data de hoje
  cpf: "529.982.247-25",
  cnpj: "11.222.333/0001-81",
  cep: "01310-100",
  email: "maria.souza@exemplo.com.br",
  phone: "(11) 91234-5678",
  select: "",
  yes_no: "Sim",
  checkbox: "Sim",
};

/** Primeiro trecho original (atributo `sample` do chip) de cada campo no documento. */
export function originalSamples(doc: DocNode | null | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  const walk = (n: DocNode) => {
    if (n.type === "field") {
      const id = String(n.attrs?.fieldId ?? "");
      const s = String(n.attrs?.sample ?? "").trim();
      if (id && s && !(id in out)) out[id] = s;
    }
    n.content?.forEach(walk);
  };
  if (doc) walk(doc);
  return out;
}

function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const specOf = (f: FieldOut): FieldSpec => ({ name: f.name, label: f.label, type: f.type, required: false, default_value: f.default_value, options: f.options, config: f.config, mask: f.mask });

/**
 * Valor de exemplo no formato que o formulário usa: texto de exibição pt-BR, data em ISO (input type=date),
 * lista pelo `value` da opção e caixa de marcar como booleano. `null` quando não há exemplo válido possível.
 */
export function exampleValue(f: FieldOut, original?: string): string | boolean | null {
  const spec = specOf(f);
  if (f.type === "checkbox") return true;
  if (f.type === "select") {
    for (const c of [f.example, f.default_value, original]) {
      if (c == null || c === "") continue;
      const { value, error } = normalizeValue(spec, c);
      if (!error && value) return String(value);
    }
    return f.options[0]?.value ?? null;
  }
  const candidates = [f.example, f.default_value, original, f.type === "date" ? todayIso() : GENERIC[f.type]];
  for (const c of candidates) {
    if (c == null || c === "") continue;
    const { value, error } = normalizeValue(spec, c);
    if (error || value === null || value === "") continue;
    if (f.type === "date") return String(value); // ISO
    if (f.type === "yes_no") return value === true ? "Sim" : "Não";
    return String(c).replace(/^R\$\s*/, "");
  }
  return null;
}

/** Valores de exemplo para todos os campos (chave = nome do campo). */
export function exampleValues(fields: FieldOut[], doc?: DocNode | null): Record<string, string | boolean> {
  const originals = originalSamples(doc);
  const out: Record<string, string | boolean> = {};
  for (const f of fields) {
    const v = exampleValue(f, originals[f.id]);
    if (v !== null) out[f.name] = v;
  }
  return out;
}
