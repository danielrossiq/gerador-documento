// Nome de arquivo previsto a partir do padrão (mesma ideia do servidor, que garante unicidade e sanitiza de verdade).
import { formatValue, normalizeValue, type FieldSpec } from "@/lib/fields/normalize";
import type { FieldOut } from "@/lib/types";

const spec = (f: FieldOut): FieldSpec => ({ name: f.name, label: f.label, type: f.type, required: false, default_value: f.default_value, options: f.options, config: f.config, mask: f.mask });

export const FILENAME_TOKENS = [
  { token: "hoje", label: "Data de hoje" },
  { token: "gerador", label: "Nome do gerador" },
  { token: "linha", label: "Número da linha (lote)" },
];

export function previewFilename(pattern: string, fields: FieldOut[], values: Record<string, unknown>, generator: string, row = 1): string {
  const tokens: Record<string, string> = { hoje: new Date().toISOString().slice(0, 10), linha: String(row).padStart(4, "0"), gerador: generator };
  for (const f of fields) {
    const { value, error } = normalizeValue(spec(f), values[f.name]);
    tokens[f.name] = error ? "" : formatValue(spec(f), value);
  }
  tokens.data ??= tokens.hoje;
  const raw = pattern.replace(/\{([a-z][a-z0-9_]*)\}/g, (_, k: string) => tokens[k] ?? "");
  return raw.replace(/[\\/:*?"<>|\x00-\x1f]/g, "-").replace(/\s+/g, "_").replace(/^[\s._-]+|[\s._-]+$/g, "") || "documento";
}

/** Códigos {…} do padrão que não correspondem a nenhum campo nem a um código especial. */
export function unknownTokens(pattern: string, fields: FieldOut[]): string[] {
  const known = new Set([...fields.map((f) => f.name), ...FILENAME_TOKENS.map((t) => t.token), "data"]);
  return [...pattern.matchAll(/\{([^}]*)\}/g)].map((m) => m[1]).filter((k) => !known.has(k));
}
