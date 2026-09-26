// Espelho de backend/app/modules/fields/normalize.py (o servidor é a autoridade; aqui é feedback imediato).
// shared/field-vectors.json é executado nas duas suítes para impedir divergência.
import type { FieldOption, FieldType } from "@/lib/types";

export type FieldSpec = {
  name: string;
  label: string;
  type: FieldType;
  required: boolean;
  default_value?: unknown;
  options: FieldOption[];
  config: Record<string, unknown>;
  mask?: string | null;
};

const MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
const TRUE_WORDS = new Set(["sim", "s", "yes", "y", "true", "1", "x", "verdadeiro", "v"]);
const FALSE_WORDS = new Set(["não", "nao", "n", "no", "false", "0", "falso", "f"]);
const VALID_DDD = new Set(
  ("11 12 13 14 15 16 17 18 19 21 22 24 27 28 31 32 33 34 35 37 38 41 42 43 44 45 46 47 48 49 " +
    "51 53 54 55 61 62 63 64 65 66 67 68 69 71 73 74 75 77 79 81 82 83 84 85 86 87 88 89 91 92 93 94 95 96 97 98 99").split(" "),
);

export const isEmpty = (v: unknown) => v === null || v === undefined || (typeof v === "string" && v.trim() === "");
export const digits = (s: string) => s.replace(/\D/g, "");

export function isValidCpf(value: string): boolean {
  const d = digits(value);
  if (d.length !== 11 || d === d[0].repeat(11)) return false;
  for (const n of [9, 10]) {
    let total = 0;
    for (let i = 0; i < n; i++) total += Number(d[i]) * (n + 1 - i);
    if (((total * 10) % 11) % 10 !== Number(d[n])) return false;
  }
  return true;
}

export const cleanCnpj = (v: string) => v.replace(/[^0-9A-Za-z]/g, "").toUpperCase();
const W1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
const W2 = [6, ...W1];
function cnpjDv(base: string, w: number[]): number {
  let total = 0;
  for (let i = 0; i < base.length; i++) total += (base.charCodeAt(i) - 48) * w[i]; // CNPJ alfanumérico: ASCII − 48
  const r = total % 11;
  return r < 2 ? 0 : 11 - r;
}
export function isValidCnpj(value: string): boolean {
  const v = cleanCnpj(value);
  if (!/^[0-9A-Z]{12}[0-9]{2}$/.test(v) || v === v[0].repeat(14)) return false;
  const d1 = cnpjDv(v.slice(0, 12), W1);
  const d2 = cnpjDv(v.slice(0, 12) + String(d1), W2);
  return v[12] === String(d1) && v[13] === String(d2);
}

export const formatCpf = (d: string) => `${d.slice(0, 3)}.${d.slice(3, 6)}.${d.slice(6, 9)}-${d.slice(9)}`;
export const formatCnpj = (v: string) => `${v.slice(0, 2)}.${v.slice(2, 5)}.${v.slice(5, 8)}/${v.slice(8, 12)}-${v.slice(12)}`;
export const formatCep = (d: string) => `${d.slice(0, 5)}-${d.slice(5)}`;
export const formatPhone = (d: string) => (d.length === 11 ? `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}` : `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`);

export function normalizePhone(value: string): string | null {
  let d = digits(value);
  if ((d.length === 12 || d.length === 13) && d.startsWith("55")) d = d.slice(2);
  if (d.length !== 10 && d.length !== 11) return null;
  if (!VALID_DDD.has(d.slice(0, 2))) return null;
  const number = d.slice(2);
  if (number.length === 9 && number[0] !== "9") return null;
  if (number.length === 8 && "01".includes(number[0])) return null;
  return d;
}

export const isValidEmail = (v: string) => v.length <= 254 && /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(v);

export function maskRegex(mask: string): RegExp {
  const out = [...mask].map((ch) => {
    if (ch === "#" || ch === "0") return "\\d";
    if (ch === "A") return "[A-Za-zÀ-ÿ]";
    if (ch === "*") return "[A-Za-zÀ-ÿ0-9]";
    return ch.replace(/[.*+?^${}()|[\]\\/-]/g, "\\$&");
  });
  return new RegExp(`^${out.join("")}$`);
}

// ------------------------------------------------------------------ decimais (strings, sem perda de precisão)

/** Interpreta ENTRADA do usuário (pt-BR). Devolve decimal canônico "-?\d+(\.\d+)?" ou null. */
export function parseDecimal(raw: unknown): string | null {
  if (typeof raw === "boolean") return null;
  if (typeof raw === "number") return Number.isFinite(raw) ? String(raw) : null;
  let s = String(raw ?? "").trim().replace("R$", "").replace(/ /g, "").replace(/ /g, "");
  if (!s) return null;
  if (s.includes(",")) s = s.replace(/\./g, "").replace(",", ".");
  else if (s.includes(".") && /^-?\d{1,3}(\.\d{3})+$/.test(s)) s = s.replace(/\./g, "");
  return /^-?\d+(\.\d+)?$/.test(s) ? s : null;
}

function splitDec(s: string): { neg: boolean; int: string; frac: string } {
  const neg = s.startsWith("-");
  const [i, f = ""] = (neg ? s.slice(1) : s).split(".");
  return { neg, int: i.replace(/^0+(?=\d)/, ""), frac: f };
}

/** Arredonda para `decimals` casas (half-even, como Decimal.quantize do Python). */
export function quantize(s: string, decimals: number): string {
  const { neg, int, frac } = splitDec(s);
  let kept = frac.slice(0, decimals).padEnd(decimals, "0");
  let n = BigInt(int + kept);
  const rest = frac.slice(decimals);
  if (rest) {
    const first = rest[0];
    const tail = rest.slice(1).replace(/0/g, "");
    const lastDigit = Number((int + kept).slice(-1) || "0");
    if (first > "5" || (first === "5" && (tail !== "" || lastDigit % 2 === 1))) n += 1n;
  }
  let str = n.toString().padStart(decimals + 1, "0");
  const ip = decimals ? str.slice(0, -decimals) : str;
  kept = decimals ? str.slice(-decimals) : "";
  str = decimals ? `${ip}.${kept}` : ip;
  const isZero = /^0+(\.0+)?$/.test(str);
  return (neg && !isZero ? "-" : "") + str;
}

function trimDec(s: string): string {
  const { neg, int, frac } = splitDec(s);
  const f = frac.replace(/0+$/, "");
  const str = f ? `${int}.${f}` : int;
  return (neg && str !== "0" ? "-" : "") + str;
}

export function brNumber(canonical: string, decimals: number | null): string {
  const d = decimals !== null ? quantize(canonical, decimals) : canonical;
  const { neg, int, frac } = splitDec(d);
  const ip = int.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return (neg ? "-" : "") + ip + (frac ? `,${frac}` : "");
}

// ------------------------------------------------------------------ datas

const pad = (n: number, w = 2) => String(n).padStart(w, "0");
function validYmd(y: number, m: number, d: number): boolean {
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.getUTCFullYear() === y && dt.getUTCMonth() === m - 1 && dt.getUTCDate() === d && y >= 1 && y <= 9999;
}

export function parseDate(raw: unknown): string | null {
  if (typeof raw === "number") {
    if (raw > 20000 && raw < 80000) {
      const dt = new Date(Date.UTC(1899, 11, 30) + Math.trunc(raw) * 86400000);
      return `${pad(dt.getUTCFullYear(), 4)}-${pad(dt.getUTCMonth() + 1)}-${pad(dt.getUTCDate())}`;
    }
    return null;
  }
  const s = String(raw ?? "").trim();
  let m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ].*)?$/);
  if (m) return validYmd(+m[1], +m[2], +m[3]) ? `${m[1]}-${pad(+m[2])}-${pad(+m[3])}` : null;
  m = s.match(/^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4}|\d{2})$/);
  if (m) {
    let y = +m[3];
    if (y < 100) y += y < 70 ? 2000 : 1900;
    return validYmd(y, +m[2], +m[1]) ? `${pad(y, 4)}-${pad(+m[2])}-${pad(+m[1])}` : null;
  }
  return null;
}

export const isoToBr = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`;

// ------------------------------------------------------------------ normalização por tipo

function toBool(raw: unknown): boolean | null {
  if (typeof raw === "boolean") return raw;
  const s = String(raw ?? "").trim().toLowerCase();
  if (TRUE_WORDS.has(s)) return true;
  if (FALSE_WORDS.has(s)) return false;
  return null;
}

const cfgNum = (cfg: Record<string, unknown>, key: string): string | null => {
  const v = cfg[key];
  return v === undefined || v === null || v === "" ? null : parseDecimal(v);
};

export function normalizeValue(fd: FieldSpec, raw: unknown): { value: unknown; error: string | null } {
  const t = fd.type;
  if (t === "checkbox") {
    if (isEmpty(raw)) return { value: false, error: fd.required ? "Marque esta opção para continuar." : null };
    const b = toBool(raw);
    if (b === null) return { value: false, error: "Valor inválido para caixa de seleção (use sim/não)." };
    if (fd.required && !b) return { value: false, error: "Marque esta opção para continuar." };
    return { value: b, error: null };
  }
  if (isEmpty(raw)) return { value: null, error: fd.required ? "Campo obrigatório." : null };
  const str = String(raw);

  if (t === "text_short") {
    const s = str.replace(/\s*[\r\n]+\s*/g, " ").trim();
    const max = Number(fd.config.max_length) || 255;
    if (s.length > max) return { value: s, error: `Use no máximo ${max} caracteres.` };
    if (fd.mask && !maskRegex(fd.mask).test(s)) return { value: s, error: `Formato inválido. Use o padrão ${fd.mask}.` };
    return { value: s, error: null };
  }
  if (t === "text_long") {
    const s = str.replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim();
    return s.length <= 20000 ? { value: s, error: null } : { value: s, error: "Use no máximo 20000 caracteres." };
  }
  if (t === "number" || t === "currency") {
    const d = parseDecimal(raw);
    if (d === null) return { value: str, error: "Informe um número válido (ex.: 1.234,56)." };
    const dec = t === "currency" ? 2 : fd.config.decimals !== undefined && fd.config.decimals !== "" && fd.config.decimals !== null ? Number(fd.config.decimals) : null;
    const canonical = dec !== null ? quantize(d, dec) : trimDec(d);
    const lo = cfgNum(fd.config, "min");
    const hi = cfgNum(fd.config, "max");
    const n = Number(d);
    if (t === "currency" && n < 0 && lo === null) return { value: canonical, error: "O valor não pode ser negativo." };
    if (lo !== null && n < Number(lo)) return { value: canonical, error: `O valor mínimo é ${brNumber(lo, dec)}.` };
    if (hi !== null && n > Number(hi)) return { value: canonical, error: `O valor máximo é ${brNumber(hi, dec)}.` };
    return { value: canonical, error: null };
  }
  if (t === "date") {
    const d = parseDate(typeof raw === "number" ? raw : str);
    return d ? { value: d, error: null } : { value: str, error: "Data inválida. Use dd/mm/aaaa." };
  }
  if (t === "cpf") {
    const s = digits(str);
    return isValidCpf(s) ? { value: s, error: null } : { value: str, error: "CPF inválido." };
  }
  if (t === "cnpj") {
    const s = cleanCnpj(str);
    return isValidCnpj(s) ? { value: s, error: null } : { value: str, error: "CNPJ inválido." };
  }
  if (t === "cep") {
    const s = digits(str);
    return s.length === 8 ? { value: s, error: null } : { value: str, error: "CEP inválido. Use 8 dígitos." };
  }
  if (t === "email") {
    const s = str.trim().toLowerCase();
    return isValidEmail(s) ? { value: s, error: null } : { value: str, error: "E-mail inválido." };
  }
  if (t === "phone") {
    const p = normalizePhone(str);
    return p ? { value: p, error: null } : { value: str, error: "Telefone inválido. Use DDD + número." };
  }
  if (t === "select") {
    const s = str.trim();
    const byValue = fd.options.find((o) => o.value === s);
    if (byValue) return { value: byValue.value, error: null };
    const low = s.toLowerCase();
    const loose = fd.options.find((o) => o.label.toLowerCase() === low || o.value.toLowerCase() === low);
    return loose ? { value: loose.value, error: null } : { value: s, error: "Opção inválida. Escolha uma das opções da lista." };
  }
  if (t === "yes_no") {
    const b = toBool(raw);
    return b !== null ? { value: b, error: null } : { value: null, error: "Responda Sim ou Não." };
  }
  return { value: str, error: `Tipo de campo desconhecido: ${t}.` };
}

/** Texto que vai para o documento a partir do valor CANÔNICO (igual ao servidor). */
export function formatValue(fd: FieldSpec, value: unknown): string {
  const t = fd.type;
  if (t === "checkbox") return String(value ? (fd.config.checked_text ?? "☒") : (fd.config.unchecked_text ?? "☐"));
  if (isEmpty(value)) return "";
  const s = String(value);
  if (t === "currency") return /^-?\d+(\.\d+)?$/.test(s) ? `R$ ${brNumber(s, 2)}` : s;
  if (t === "number") {
    if (!/^-?\d+(\.\d+)?$/.test(s)) return s;
    const dec = fd.config.decimals;
    return brNumber(s, dec !== undefined && dec !== null && dec !== "" ? Number(dec) : null);
  }
  if (t === "date") {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
    return fd.config.date_format === "long" ? `${Number(s.slice(8, 10))} de ${MONTHS[Number(s.slice(5, 7)) - 1]} de ${s.slice(0, 4)}` : isoToBr(s);
  }
  if (t === "cpf") return s.length === 11 ? formatCpf(s) : s;
  if (t === "cnpj") return s.length === 14 ? formatCnpj(s) : s;
  if (t === "cep") return s.length === 8 ? formatCep(s) : s;
  if (t === "phone") return s.length === 10 || s.length === 11 ? formatPhone(s) : s;
  if (t === "select") return fd.options.find((o) => o.value === s)?.label ?? s;
  if (t === "yes_no") return value === true ? "Sim" : "Não";
  return s;
}

/** Valida uma linha (por nome de campo) aplicando valor padrão a vazios. */
export function validateRow(specs: FieldSpec[], row: Record<string, unknown>): { values: Record<string, unknown>; errors: Record<string, string> } {
  const values: Record<string, unknown> = {};
  const errors: Record<string, string> = {};
  for (const fd of specs) {
    let raw = row[fd.name];
    if (isEmpty(raw) && !isEmpty(fd.default_value)) raw = fd.default_value;
    const { value, error } = normalizeValue(fd, raw);
    values[fd.name] = value;
    if (error) errors[fd.name] = error;
  }
  return { values, errors };
}
