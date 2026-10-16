import type { FieldSpec } from "@/lib/fields/normalize";
import {
  brNumber,
  cleanCnpj,
  digits,
  formatCep,
  formatCnpj,
  formatCpf,
  formatOab,
  formatPhone,
  isoToBr,
  normalizeOab,
  normalizeValue,
  parseDate,
  parseDecimal,
} from "@/lib/fields/normalize";

/** Aplica um padrão com `#` (dígito) e `A` (alfanumérico) progressivamente ao texto digitado. */
function applyPattern(pattern: string, chars: string): string {
  let out = "";
  let i = 0;
  for (const p of pattern) {
    if (i >= chars.length) break;
    if (p === "#" || p === "A") {
      out += chars[i++];
    } else out += p;
  }
  return out;
}

/** Máscara ao vivo enquanto o usuário digita. Tipos sem máscara devolvem o texto como está. */
export function liveMask(type: string, text: string): string {
  switch (type) {
    case "cpf":
      return applyPattern("###.###.###-##", digits(text).slice(0, 11));
    case "cnpj":
      return applyPattern("AA.AAA.AAA/AAAA-##", cleanCnpj(text).slice(0, 14));
    case "cep":
      return applyPattern("#####-###", digits(text).slice(0, 8));
    case "phone": {
      let d = digits(text);
      if ((d.length > 11 && d.startsWith("55")) || (d.length === 13 && d.startsWith("55"))) d = d.slice(2);
      d = d.slice(0, 11);
      return d.length > 10 ? applyPattern("(##) #####-####", d) : applyPattern("(##) ####-####", d);
    }
    case "date": {
      const d = digits(text).slice(0, 8);
      return applyPattern("##/##/####", d);
    }
    default:
      return text;
  }
}

/** Forma de exibição definitiva (ao confirmar/colar na grade). Se inválido, mantém o texto digitado. */
export function displayFor(fd: FieldSpec, text: string): string {
  const t = text.trim();
  if (t === "") return "";
  switch (fd.type) {
    case "cpf": {
      const d = digits(t);
      return d.length === 11 ? formatCpf(d) : liveMask("cpf", t);
    }
    case "cnpj": {
      const v = cleanCnpj(t);
      return v.length === 14 ? formatCnpj(v) : liveMask("cnpj", t);
    }
    case "cep": {
      const d = digits(t);
      return d.length === 8 ? formatCep(d) : liveMask("cep", t);
    }
    case "phone": {
      const { value, error } = normalizeValue(fd, t);
      return !error && typeof value === "string" ? formatPhone(value) : liveMask("phone", t);
    }
    case "oab": {
      const o = normalizeOab(t);
      return o ? formatOab(o) : t;
    }
    case "date": {
      const iso = parseDate(t);
      return iso ? isoToBr(iso) : t;
    }
    case "currency":
    case "number": {
      const d = parseDecimal(t);
      if (d === null) return t;
      const dec = fd.type === "currency" ? 2 : fd.config.decimals !== undefined && fd.config.decimals !== "" && fd.config.decimals !== null ? Number(fd.config.decimals) : null;
      return brNumber(d, dec);
    }
    case "yes_no": {
      const { value, error } = normalizeValue(fd, t);
      return !error ? (value === true ? "Sim" : "Não") : t;
    }
    case "checkbox": {
      const { value, error } = normalizeValue({ ...fd, required: false }, t);
      return !error && value === true ? "Sim" : !error ? "" : t;
    }
    case "select": {
      const { value, error } = normalizeValue(fd, t);
      return !error ? (fd.options.find((o) => o.value === value)?.label ?? t) : t;
    }
    case "email":
      return t.toLowerCase();
    case "text_short":
      return t.replace(/\s*[\r\n]+\s*/g, " ");
    default:
      return t;
  }
}

/** Sugere o tipo de campo a partir do texto selecionado no documento. */
export function detectType(text: string): import("@/lib/types").FieldType {
  const t = text.trim();
  if (/^\d{3}\.\d{3}\.\d{3}-\d{2}$/.test(t) || (/^\d{11}$/.test(t))) return "cpf";
  if (/^[0-9A-Z]{2}\.[0-9A-Z]{3}\.[0-9A-Z]{3}\/[0-9A-Z]{4}-\d{2}$/.test(t)) return "cnpj";
  if (/^\d{5}-\d{3}$/.test(t)) return "cep";
  if (/^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(t)) return "email";
  if (/^R\$\s?[\d.]+(,\d{2})?$/.test(t)) return "currency";
  if (/^\(?\d{2}\)?\s?9?\d{4}-?\d{4}$/.test(t)) return "phone";
  if (/^\d{1,2}\/\d{1,2}\/\d{2,4}$/.test(t) || /^\d{1,2} de [a-zç]+ de \d{4}$/i.test(t)) return "date";
  if (/^(sim|não|nao)$/i.test(t)) return "yes_no";
  if (/^-?\d+([.,]\d+)?$/.test(t)) return "number";
  if (t.length > 120 || t.includes("\n")) return "text_long";
  return "text_short";
}

export function guessLabel(before: string, type: string, text: string): string {
  const m = before.match(/([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ ]{1,40})\s*[:\-–]\s*$/);
  if (m) {
    const l = m[1].trim();
    return l.charAt(0).toUpperCase() + l.slice(1).toLowerCase();
  }
  const byType: Record<string, string> = { cpf: "CPF", cnpj: "CNPJ", cep: "CEP", email: "E-mail", phone: "Telefone", currency: "Valor", date: "Data", number: "Número" };
  return byType[type] ?? (text.length <= 30 ? "" : "");
}
