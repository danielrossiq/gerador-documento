// O que falta configurar num modelo — calculado no cliente a partir dos campos e do documento.
// Usado no editor (avisos por campo), na revisão (lista de pendências) e no painel.
import type { DocNode, FieldOut } from "@/lib/types";

export type FieldLike = Pick<FieldOut, "id" | "label" | "type" | "required" | "options" | "position">;

export type IssueKind = "empty_label" | "duplicate_label" | "empty_options" | "not_in_document";
export type FieldIssue = { fieldId: string; kind: IssueKind; severity: "error" | "warning"; message: string };

/** Compara rótulos como a pessoa leria: sem acento, sem diferença de maiúsculas e espaços. */
export function normalizeLabel(label: string): string {
  return label.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/\s+/g, " ").trim();
}

/** Outros campos com o mesmo rótulo (ignorando `exceptId`). */
export function sameLabelFields<T extends Pick<FieldOut, "id" | "label">>(fields: T[], label: string, exceptId?: string): T[] {
  const n = normalizeLabel(label);
  if (!n) return [];
  return fields.filter((f) => f.id !== exceptId && normalizeLabel(f.label) === n);
}

/**
 * Pendências por campo. `counts` = ocorrências de cada campo no documento (quando conhecidas).
 * Erro: o resultado sai errado ou não dá para preencher. Aviso: funciona, mas confunde quem preenche.
 */
export function fieldIssues(fields: FieldLike[], counts?: Record<string, number>): FieldIssue[] {
  const out: FieldIssue[] = [];
  const byLabel = new Map<string, FieldLike[]>();
  for (const f of fields) {
    const n = normalizeLabel(f.label);
    if (n) byLabel.set(n, [...(byLabel.get(n) ?? []), f]);
  }
  for (const f of fields) {
    if (!f.label.trim()) out.push({ fieldId: f.id, kind: "empty_label", severity: "error", message: "Campo sem nome." });
    const twins = byLabel.get(normalizeLabel(f.label)) ?? [];
    if (twins.length > 1) {
      out.push({
        fieldId: f.id,
        kind: "duplicate_label",
        severity: "warning",
        message: `Há ${twins.length} campos chamados “${f.label}”. No formulário e na planilha eles aparecem iguais — renomeie ou use o mesmo campo nos dois trechos.`,
      });
    }
    if (f.type === "select" && f.options.filter((o) => o.label.trim()).length === 0) {
      out.push({ fieldId: f.id, kind: "empty_options", severity: "error", message: "Lista de opções sem nenhuma opção: não há o que escolher ao preencher." });
    }
    if (counts && !(counts[f.id] > 0)) {
      out.push({ fieldId: f.id, kind: "not_in_document", severity: "warning", message: "Não aparece no documento: o que for preenchido não vai para lugar nenhum. Insira-o no texto ou exclua-o." });
    }
  }
  return out;
}

export function issuesByField(issues: FieldIssue[]): Record<string, FieldIssue[]> {
  const m: Record<string, FieldIssue[]> = {};
  for (const i of issues) (m[i.fieldId] ??= []).push(i);
  return m;
}

/** Ids dos campos na ordem em que aparecem pela primeira vez no documento (cabeçalho → corpo → rodapé). */
export function documentOrder(doc: DocNode): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  const walk = (n: DocNode) => {
    if (n.type === "field") {
      const id = String(n.attrs?.fieldId ?? "");
      if (id && !seen.has(id)) {
        seen.add(id);
        out.push(id);
      }
    }
    n.content?.forEach(walk);
  };
  walk(doc);
  return out;
}

/** Contagem de ocorrências de cada campo no documento. */
export function occurrenceCounts(doc: DocNode): Record<string, number> {
  const c: Record<string, number> = {};
  const walk = (n: DocNode) => {
    if (n.type === "field") {
      const id = String(n.attrs?.fieldId ?? "");
      if (id) c[id] = (c[id] ?? 0) + 1;
    }
    n.content?.forEach(walk);
  };
  walk(doc);
  return c;
}

/** Ordena como no documento; campos que não aparecem nele vão para o fim, mantendo a ordem atual entre si. */
export function sortByDocument<T extends { id: string }>(fields: T[], order: string[]): T[] {
  const idx = new Map(order.map((id, i) => [id, i]));
  return fields
    .map((f, i) => ({ f, k: idx.has(f.id) ? idx.get(f.id)! : order.length + i }))
    .sort((a, b) => a.k - b.k)
    .map((x) => x.f);
}

/** A lista está na mesma ordem do documento? (usado para manter a ordem sincronizada até a pessoa personalizar). */
export function isDocumentOrder(fields: { id: string }[], order: string[]): boolean {
  const sorted = sortByDocument(fields, order);
  return sorted.every((f, i) => f.id === fields[i].id);
}
