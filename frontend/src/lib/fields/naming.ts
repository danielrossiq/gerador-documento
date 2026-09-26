/** 'Nome do contratante' → 'nome_do_contratante' (espelho de to_snake_case do backend; o servidor garante unicidade). */
export function toSnake(text: string, fallback = "campo"): string {
  let s = text.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  if (!s) s = fallback;
  if (!/^[a-z]/.test(s)) s = `${fallback}_${s}`;
  return s.slice(0, 60).replace(/_+$/, "");
}

export const RESERVED_NAMES = ["hoje", "linha", "gerador"];
export const NAME_RE = /^[a-z][a-z0-9_]{0,62}$/;
