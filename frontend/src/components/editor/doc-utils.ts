import type { Node as PMNode } from "@tiptap/pm/model";
import type { Editor } from "@tiptap/core";

/**
 * Modelo de offsets idêntico ao do servidor (backend/app/docx_engine/nodes.py):
 * texto → seu texto · campo → `sample` · átomo/quebra → 1 caractere.
 */
export function nodeTextLen(n: PMNode): number {
  if (n.isText) return n.text!.length;
  if (n.type.name === "field") return String(n.attrs.sample ?? "").length;
  return 1;
}

export function findBlock(doc: PMNode, blockKey: string): { node: PMNode; pos: number } | null {
  let found: { node: PMNode; pos: number } | null = null;
  doc.descendants((node, pos) => {
    if (found) return false;
    if (node.type.name === "paragraph" && node.attrs.blockKey === blockKey) {
      found = { node, pos };
      return false;
    }
    return true;
  });
  return found;
}

/** Converte offset de texto do bloco em posição do ProseMirror. */
export function offsetToPos(block: { node: PMNode; pos: number }, offset: number): number {
  let acc = 0;
  let p = block.pos + 1;
  for (let i = 0; i < block.node.childCount; i++) {
    const child = block.node.child(i);
    const len = nodeTextLen(child);
    if (offset <= acc + len) {
      if (child.isText) return p + (offset - acc);
      return offset - acc <= 0 ? p : p + child.nodeSize;
    }
    acc += len;
    p += child.nodeSize;
  }
  return p;
}

export function rangeOfOffsets(editor: Editor, blockKey: string, start: number, end: number): { from: number; to: number } | null {
  const block = findBlock(editor.state.doc, blockKey);
  if (!block) return null;
  return { from: offsetToPos(block, start), to: offsetToPos(block, end) };
}

export function scrollToPos(editor: Editor, pos: number) {
  try {
    const { node } = editor.view.domAtPos(Math.min(pos, editor.state.doc.content.size));
    const el = node.nodeType === 1 ? (node as Element) : node.parentElement;
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
  } catch {
    /* posição fora da vista: ignorar */
  }
}

export type FieldNodeInfo = { pos: number; fieldId: string };
export function fieldNodes(doc: PMNode, fieldId?: string): FieldNodeInfo[] {
  const out: FieldNodeInfo[] = [];
  doc.descendants((node, pos) => {
    if (node.type.name === "field" && (!fieldId || node.attrs.fieldId === fieldId)) out.push({ pos, fieldId: node.attrs.fieldId });
  });
  return out;
}

export function countFieldNodes(doc: PMNode): Record<string, number> {
  const c: Record<string, number> = {};
  for (const n of fieldNodes(doc)) c[n.fieldId] = (c[n.fieldId] ?? 0) + 1;
  return c;
}

export type OutlineItem = { key: string; label: string; level: number; kind: "part" | "heading" | "table" };

export function buildOutline(doc: PMNode): OutlineItem[] {
  const items: OutlineItem[] = [];
  let tables = 0;
  doc.descendants((node) => {
    if (node.type.name === "docPart") {
      items.push({ key: `part:${node.attrs.part}`, label: node.attrs.label, level: 0, kind: "part" });
    } else if (node.type.name === "paragraph" && node.attrs.heading) {
      const t = node.textContent.trim();
      if (t) items.push({ key: String(node.attrs.blockKey), label: t.slice(0, 60), level: Number(node.attrs.heading), kind: "heading" });
    } else if (node.type.name === "table") {
      tables += 1;
      items.push({ key: String(node.attrs.blockKey), label: `Tabela ${tables}`, level: 1, kind: "table" });
    }
    return true;
  });
  return items;
}
