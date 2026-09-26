"use client";

import { NodeViewWrapper, type NodeViewProps } from "@tiptap/react";
import { AlertTriangle, Type } from "lucide-react";
import { useContext } from "react";
import { FieldsContext } from "@/components/editor/context";
import { FIELD_TYPE_META } from "@/lib/fields/meta";

/**
 * Chip de um campo no documento. Não depende só de cor: tem ícone por tipo, rótulo em texto e, quando o campo
 * foi removido, um ícone de alerta. Nome, tipo e estado aparecem ao passar o mouse/focar e no aria-label.
 */
export function FieldChip({ node }: NodeViewProps) {
  const ctx = useContext(FieldsContext);
  const id = String(node.attrs.fieldId);
  const f = ctx.fields[id];
  const meta = f ? FIELD_TYPE_META[f.type] : null;
  const Icon = meta?.icon ?? Type;
  const selected = ctx.selectedId === id;
  const issues = ctx.issues[id] ?? [];
  const label = f?.label ?? (String(node.attrs.sample || "") || "Campo removido");
  const state = !f ? "Campo removido — remova este trecho" : f.required ? "Obrigatório" : "Opcional";
  const pend = issues.length ? `\n⚠ ${issues.map((i) => (i.kind === "duplicate_label" ? "Nome repetido" : i.kind === "empty_options" ? "Lista sem opções" : "Revisar")).join(", ")}` : "";
  const tooltip = `${label}\nTipo: ${meta?.label ?? "desconhecido"}\n${state}\nTexto original: ${String(node.attrs.sample || "—")}${pend}\nClique para configurar`;
  return (
    <NodeViewWrapper
      as="span"
      className="field-chip"
      data-selected={selected}
      data-missing={!f}
      data-issue={issues.length > 0 || undefined}
      data-field-id={id}
      data-tooltip={tooltip}
      aria-label={`Campo ${label}, ${meta?.label ?? "tipo desconhecido"}, ${state}${issues.length ? ", precisa de atenção" : ""}`}
      contentEditable={false}
      onClick={() => ctx.select(id)}
    >
      {f ? <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden /> : <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden />}
      <span className="chip-label">{label}</span>
      {f && issues.length > 0 && <AlertTriangle className="h-3 w-3 shrink-0 text-warning" aria-hidden />}
    </NodeViewWrapper>
  );
}
