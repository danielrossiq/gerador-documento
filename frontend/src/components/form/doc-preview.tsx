"use client";

import { Fragment, type ReactNode } from "react";
import { formatValue, normalizeValue, type FieldSpec } from "@/lib/fields/normalize";
import type { DocNode, FieldOut } from "@/lib/types";

/**
 * Prévia somente leitura: renderiza o mesmo JSON do editor, trocando cada campo pelo valor já formatado
 * (mesma regra do servidor — shared/field-vectors.json). É uma aproximação HTML; o arquivo final vem do DOCX/PDF.
 */
export function DocPreview({
  doc,
  fields,
  values,
  found,
}: {
  doc: DocNode;
  fields: FieldOut[];
  values: Record<string, unknown>;
  /** Modo "campos encontrados" (teste grátis da landing): mostra o trecho original destacado, com o rótulo. */
  found?: Record<string, string>;
}) {
  const byId = new Map(fields.map((f) => [f.id, f]));

  function fieldText(fieldId: string): { text: string; empty: boolean } {
    const f = byId.get(fieldId);
    if (!f) return { text: "", empty: true };
    const spec: FieldSpec = { ...f, default_value: f.default_value };
    let raw = values[f.name];
    if ((raw === undefined || raw === null || raw === "") && f.default_value) raw = f.default_value;
    const { value, error } = normalizeValue({ ...spec, required: false }, raw);
    if (error || value === null || value === "") return { text: `[${f.label}]`, empty: true };
    return { text: formatValue(spec, value), empty: false };
  }

  function marks(n: DocNode, child: ReactNode): ReactNode {
    let out = child;
    for (const m of n.marks ?? []) {
      if (m.type === "bold") out = <strong>{out}</strong>;
      else if (m.type === "italic") out = <em>{out}</em>;
      else if (m.type === "underline") out = <u>{out}</u>;
      else if (m.type === "strike") out = <s>{out}</s>;
    }
    return out;
  }

  function render(n: DocNode, key: string | number): ReactNode {
    const kids = () => (n.content ?? []).map((c, i) => render(c, i));
    switch (n.type) {
      case "docPart":
        return (
          <section key={key} className="doc-part" data-kind={String(n.attrs?.kind)} data-label={String(n.attrs?.label)}>
            {kids()}
          </section>
        );
      case "paragraph": {
        const a = n.attrs ?? {};
        return (
          <p key={key} data-heading={a.heading ? String(a.heading) : undefined} data-list={a.list ? "true" : undefined} style={a.align ? { textAlign: a.align as "left" } : undefined}>
            {n.content?.length ? kids() : <br />}
          </p>
        );
      }
      case "text":
        return <Fragment key={key}>{marks(n, n.text)}</Fragment>;
      case "hardBreak":
        return <br key={key} />;
      case "field": {
        if (found) {
          const label = found[String(n.attrs?.fieldId)] ?? "";
          return (
            <Fragment key={key}>
              {marks(
                n,
                <mark className="pv-field" data-found="true" title={label} data-testid="pv-field">
                  {String(n.attrs?.sample ?? "")}
                  <span className="sr-only"> (campo: {label})</span>
                </mark>,
              )}
            </Fragment>
          );
        }
        const { text, empty } = fieldText(String(n.attrs?.fieldId));
        return (
          <Fragment key={key}>
            {marks(n, <mark className="pv-field" data-empty={empty} data-testid="pv-field">{text}</mark>)}
          </Fragment>
        );
      }
      case "docAtom":
        return (
          <span key={key} className="doc-atom" data-kind={String(n.attrs?.kind)}>
            {n.attrs?.kind === "pagebreak" ? "── Quebra de página ──" : `▣ ${n.attrs?.label}`}
          </span>
        );
      case "docOpaque":
        return <div key={key} className="doc-opaque">▣ {String(n.attrs?.label)}</div>;
      case "table":
        return (
          <table key={key}>
            <tbody>{kids()}</tbody>
          </table>
        );
      case "tableRow":
        return <tr key={key}>{kids()}</tr>;
      case "tableCell":
        return (
          <td key={key} colSpan={Number(n.attrs?.colspan) || 1} rowSpan={Number(n.attrs?.rowspan) || 1}>
            {kids()}
          </td>
        );
      default:
        return null;
    }
  }

  return (
    <div className={found ? "doc-page doc-compact" : "doc-page"} aria-label="Prévia do documento" data-testid="doc-preview">
      <div className="ProseMirror">{(doc.content ?? []).map((n, i) => render(n, i))}</div>
    </div>
  );
}
