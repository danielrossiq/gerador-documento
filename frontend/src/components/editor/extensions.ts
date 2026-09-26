import { Extension, mergeAttributes, Node } from "@tiptap/core";
import Document from "@tiptap/extension-document";
import Paragraph from "@tiptap/extension-paragraph";
import { Table, TableCell, TableHeader, TableRow } from "@tiptap/extension-table";
import type { Node as PMNode } from "@tiptap/pm/model";
import { NodeSelection, Plugin, PluginKey, type EditorState, type Transaction } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import { ReactNodeViewRenderer } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { FieldChip } from "@/components/editor/field-chip";

// ------------------------------------------------------------------ estrutura do documento

export const DocDocument = Document.extend({ content: "docPart+" });

/** Região do arquivo Word: cabeçalho, corpo ou rodapé. */
export const DocPart = Node.create({
  name: "docPart",
  content: "block+",
  isolating: true,
  defining: true,
  selectable: false,
  addAttributes() {
    return { part: { default: null }, label: { default: "" }, kind: { default: "body" } };
  },
  parseHTML() {
    return [{ tag: "section[data-part]" }];
  },
  renderHTML({ node }) {
    return ["section", { class: "doc-part", "data-part": node.attrs.part, "data-kind": node.attrs.kind, "data-label": node.attrs.label, role: "group", "aria-label": node.attrs.label }, 0];
  },
});

/** Parágrafo com chave estável do bloco no DOCX (`blockKey`); parágrafos novos nascem sem chave (keepOnSplit: false). */
export const DocParagraph = Paragraph.extend({
  addAttributes() {
    return {
      blockKey: {
        default: null,
        keepOnSplit: false,
        parseHTML: (el) => el.getAttribute("data-block-key"),
        renderHTML: (a) => (a.blockKey ? { "data-block-key": a.blockKey } : {}),
      },
      heading: { default: null, parseHTML: (el) => el.getAttribute("data-heading"), renderHTML: (a) => (a.heading ? { "data-heading": String(a.heading) } : {}) },
      align: { default: null, renderHTML: (a) => (a.align ? { style: `text-align:${a.align}` } : {}) },
      list: { default: null, parseHTML: (el) => el.getAttribute("data-list") === "true" || null, renderHTML: (a) => (a.list ? { "data-list": "true" } : {}) },
      level: { default: null, rendered: false },
      style: { default: null, rendered: false },
    };
  },
});

export const DocTable = Table.extend({
  addAttributes() {
    return { ...this.parent?.(), blockKey: { default: null, parseHTML: (el) => el.getAttribute("data-block-key"), renderHTML: (a) => (a.blockKey ? { "data-block-key": a.blockKey } : {}) } };
  },
});

export const DocTableCell = TableCell.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      container: { default: null, parseHTML: (el) => el.getAttribute("data-container"), renderHTML: (a) => (a.container ? { "data-container": a.container } : {}) },
    };
  },
});

/** Imagem, quebra de página, campo complexo do Word… preservados na posição, mas não editáveis. */
export const DocAtom = Node.create({
  name: "docAtom",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,
  addAttributes() {
    return { ref: { default: null }, kind: { default: "" }, label: { default: "Elemento" } };
  },
  parseHTML() {
    return [{ tag: "span[data-doc-atom]" }];
  },
  renderHTML({ node, HTMLAttributes }) {
    const pb = node.attrs.kind === "pagebreak";
    return [
      "span",
      mergeAttributes(HTMLAttributes, { class: "doc-atom", "data-doc-atom": "", "data-kind": node.attrs.kind, "data-ref": node.attrs.ref, contenteditable: "false", title: `${node.attrs.label} (preservado, não editável)` }),
      pb ? "── Quebra de página ──" : `▣ ${node.attrs.label}`,
    ];
  },
});

export const DocOpaque = Node.create({
  name: "docOpaque",
  group: "block",
  atom: true,
  selectable: true,
  addAttributes() {
    return { blockKey: { default: null }, label: { default: "Elemento avançado" } };
  },
  parseHTML() {
    return [{ tag: "div[data-doc-opaque]" }];
  },
  renderHTML({ node }) {
    return ["div", { class: "doc-opaque", "data-doc-opaque": "", "data-block-key": node.attrs.blockKey, contenteditable: "false" }, `▣ ${node.attrs.label}`];
  },
});

// ------------------------------------------------------------------ campo (chip)

export const FieldNode = Node.create<{ onOpen?: (fieldId: string) => void }>({
  name: "field",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,
  draggable: false,
  addOptions() {
    return { onOpen: undefined };
  },
  addAttributes() {
    return { fieldId: { default: null }, sample: { default: "" } };
  },
  parseHTML() {
    return [{ tag: "span[data-field-id]" }];
  },
  renderHTML({ node }) {
    return ["span", { class: "field-chip", "data-field-id": node.attrs.fieldId }, String(node.attrs.sample || "campo")];
  },
  addNodeView() {
    return ReactNodeViewRenderer(FieldChip, { as: "span" });
  },
  addKeyboardShortcuts() {
    // Enter sobre um chip selecionado (via setas) abre a configuração do campo: acessível por teclado.
    return {
      Enter: ({ editor }) => {
        const sel = editor.state.selection;
        if (sel instanceof NodeSelection && sel.node.type.name === "field") {
          this.options.onOpen?.(String(sel.node.attrs.fieldId));
          return true;
        }
        return false;
      },
    };
  },
});

// ------------------------------------------------------------------ guarda de estrutura

function structureSignature(doc: PMNode): string {
  const parts: string[] = [];
  doc.descendants((n) => {
    switch (n.type.name) {
      case "docPart": parts.push(`P:${n.attrs.part}`); break;
      case "table": parts.push(`T:${n.attrs.blockKey}`); break;
      case "tableRow": parts.push("R"); break;
      case "tableCell": parts.push(`C:${n.attrs.container}:${n.attrs.colspan}:${n.attrs.rowspan}`); break;
      case "docOpaque": parts.push(`O:${n.attrs.blockKey}`); break;
    }
  });
  return parts.join("|");
}

/** No MVP tabelas, cabeçalho/rodapé e blocos avançados não mudam de estrutura: transações que tentem isso são recusadas. */
export const StructureGuard = Extension.create({
  name: "structureGuard",
  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: new PluginKey("structureGuard"),
        filterTransaction(tr: Transaction, state: EditorState) {
          if (!tr.docChanged || tr.getMeta("allowStructure")) return true;
          return structureSignature(state.doc) === structureSignature(tr.doc);
        },
      }),
    ];
  },
});

// ------------------------------------------------------------------ realces (busca e sugestões)

type Range = { from: number; to: number };
/** query/current: busca · ranges: sugestão sob o mouse · pending: trecho que está virando campo (painel aberto). */
export const highlightKey = new PluginKey<{ query: string; current: number; ranges: Range[]; pending: Range | null }>("docHighlights");

export function findMatches(doc: PMNode, query: string): { from: number; to: number }[] {
  const q = query.trim().toLowerCase();
  const out: { from: number; to: number }[] = [];
  if (q.length < 2) return out;
  doc.descendants((node, pos) => {
    if (!node.isText) return true;
    const text = node.text!.toLowerCase();
    let i = text.indexOf(q);
    while (i >= 0) {
      out.push({ from: pos + i, to: pos + i + q.length });
      i = text.indexOf(q, i + q.length);
    }
    return true;
  });
  return out;
}

export const Highlights = Extension.create({
  name: "docHighlights",
  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: highlightKey,
        state: {
          init: () => ({ query: "", current: 0, ranges: [] as Range[], pending: null as Range | null }),
          apply(tr, value) {
            const meta = tr.getMeta(highlightKey);
            const next = meta ? { ...value, ...meta } : value;
            if (tr.docChanged && next.ranges.length) {
              next.ranges = next.ranges.map((r: Range) => ({ from: tr.mapping.map(r.from), to: tr.mapping.map(r.to) }));
            }
            if (tr.docChanged && next.pending) next.pending = { from: tr.mapping.map(next.pending.from), to: tr.mapping.map(next.pending.to) };
            return next;
          },
        },
        props: {
          decorations(state) {
            const s = highlightKey.getState(state);
            if (!s) return null;
            const decos: Decoration[] = [];
            findMatches(state.doc, s.query).forEach((m, i) => decos.push(Decoration.inline(m.from, m.to, { class: `search-hl${i === s.current ? " current" : ""}` })));
            for (const r of s.ranges) if (r.to > r.from) decos.push(Decoration.inline(r.from, r.to, { class: "suggestion-hl" }));
            if (s.pending && s.pending.to > s.pending.from) decos.push(Decoration.inline(s.pending.from, s.pending.to, { class: "pending-hl" }));
            return decos.length ? DecorationSet.create(state.doc, decos) : null;
          },
        },
      }),
    ];
  },
});

// ------------------------------------------------------------------ conjunto completo

export function buildExtensions(opts: { onOpenField: (id: string) => void; onFieldShortcut: () => void }) {
  return [
    StarterKit.configure({
      document: false, paragraph: false, heading: false, blockquote: false, bulletList: false, orderedList: false, listItem: false,
      listKeymap: false, codeBlock: false, code: false, horizontalRule: false, link: false, trailingNode: false,
    }),
    DocDocument,
    DocPart,
    DocParagraph,
    DocTable.configure({ resizable: false, allowTableNodeSelection: false }),
    TableRow,
    TableHeader, // exigido pelo esquema de tableRow (o servidor só emite tableCell)
    DocTableCell,
    DocAtom,
    DocOpaque,
    FieldNode.configure({ onOpen: opts.onOpenField }),
    StructureGuard,
    Highlights,
    Extension.create({
      name: "fieldShortcut",
      addKeyboardShortcuts() {
        return { "Mod-Shift-f": () => { opts.onFieldShortcut(); return true; } };
      },
    }),
  ];
}
