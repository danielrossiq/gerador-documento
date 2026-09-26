"use client";

import type { Editor } from "@tiptap/core";
import { NodeSelection } from "@tiptap/pm/state";
import { useEditorState } from "@tiptap/react";
import { Bold, Italic, Sparkles, Strikethrough, Underline, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";

export type PendingSelection = { from: number; to: number; text: string; before: string };

/** Ajusta o intervalo para não incluir espaços nas pontas (o campo vale só pelo trecho útil). */
export function selectionForField(editor: Editor): PendingSelection | null {
  const { from, to, empty } = editor.state.selection;
  if (empty || editor.state.selection instanceof NodeSelection) return null;
  const doc = editor.state.doc;
  const $from = doc.resolve(from);
  const $to = doc.resolve(to);
  if ($from.parent !== $to.parent || $from.parent.type.name !== "paragraph") return null;
  const raw = doc.textBetween(from, to, "\n", "￼");
  if (raw.includes("\n") || raw.includes("￼")) return null;
  const lead = raw.length - raw.trimStart().length;
  const trail = raw.length - raw.trimEnd().length;
  const text = raw.trim();
  if (!text) return null;
  const f = from + lead;
  const t = to - trail;
  const start = $from.start();
  const before = doc.textBetween(start, f, "\n", "￼");
  return { from: f, to: t, text, before };
}

export function BubbleToolbar({ editor, onTransform }: { editor: Editor; onTransform: (s: PendingSelection) => void }) {
  const [toolbarFocused, setToolbarFocused] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  const st = useEditorState({
    editor,
    selector: ({ editor: e }) => ({
      from: e.state.selection.from,
      to: e.state.selection.to,
      empty: e.state.selection.empty,
      isNode: e.state.selection instanceof NodeSelection,
      focused: e.isFocused,
      bold: e.isActive("bold"),
      italic: e.isActive("italic"),
      underline: e.isActive("underline"),
      strike: e.isActive("strike"),
      canField: !!selectionForField(e),
    }),
  });

  const visible = !st.empty && !st.isNode && (st.focused || toolbarFocused);

  const place = useCallback(() => {
    if (!visible) return setPos(null);
    try {
      const a = editor.view.coordsAtPos(st.from);
      const b = editor.view.coordsAtPos(st.to);
      const top = Math.min(a.top, b.top) - 52;
      const mid = (a.left + b.right) / 2;
      const w = ref.current?.offsetWidth ?? 420;
      setPos({ top: Math.max(8, top < 8 ? Math.max(a.bottom, b.bottom) + 10 : top), left: Math.min(Math.max(8, mid - w / 2), window.innerWidth - w - 8) });
    } catch {
      setPos(null);
    }
  }, [editor, st.from, st.to, visible]);

  useLayoutEffect(place, [place]);
  useEffect(() => {
    if (!visible) return;
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [visible, place]);

  // Alt+F10 leva o foco do teclado ao menu (padrão WAI-ARIA para barras de ferramentas flutuantes)
  useEffect(() => {
    const dom = editor.view.dom;
    const onKey = (e: KeyboardEvent) => {
      if (e.altKey && e.key === "F10" && ref.current) {
        e.preventDefault();
        ref.current.querySelector<HTMLButtonElement>("button:not([disabled])")?.focus();
      }
    };
    dom.addEventListener("keydown", onKey);
    return () => dom.removeEventListener("keydown", onKey);
  }, [editor]);

  function onToolbarKey(e: React.KeyboardEvent) {
    const buttons = Array.from(ref.current?.querySelectorAll<HTMLButtonElement>("button:not([disabled])") ?? []);
    const i = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      buttons[(i + (e.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length]?.focus();
    } else if (e.key === "Escape") {
      e.preventDefault();
      editor.commands.focus();
    }
  }

  if (!visible || !pos) return null;

  const keep = (e: React.MouseEvent) => e.preventDefault(); // não tira o foco/seleção do documento
  const btn = "grid h-8 min-w-8 place-items-center rounded px-2 text-sm hover:bg-white/15 focus-visible:outline-white aria-pressed:bg-white/25";

  return createPortal(
    <div
      ref={ref}
      role="toolbar"
      aria-label="Ações para o texto selecionado"
      style={{ position: "fixed", top: pos.top, left: pos.left, zIndex: 45 }}
      className="flex items-center gap-0.5 rounded-lg bg-[#1f2330] p-1 text-white shadow-md"
      onKeyDown={onToolbarKey}
      onFocus={() => setToolbarFocused(true)}
      onBlur={(e) => !e.currentTarget.contains(e.relatedTarget as Node) && setToolbarFocused(false)}
    >
      <button
        type="button"
        onMouseDown={keep}
        onClick={() => {
          const s = selectionForField(editor);
          if (s) onTransform(s);
        }}
        disabled={!st.canField}
        title={st.canField ? "Transformar o trecho selecionado em campo (Ctrl+Shift+F)" : "Selecione um trecho dentro de um único parágrafo, sem quebras de linha"}
        className={cn("flex h-8 items-center gap-1.5 rounded bg-primary px-3 text-sm font-semibold hover:bg-primary-hover disabled:opacity-50")}
      >
        <Sparkles className="h-4 w-4" aria-hidden /> Transformar em campo
      </button>
      <span aria-hidden className="mx-1 h-5 w-px bg-white/25" />
      <button type="button" onMouseDown={keep} onClick={() => editor.chain().focus().toggleBold().run()} aria-pressed={st.bold} aria-label="Negrito" title="Negrito (Ctrl+B)" className={btn}>
        <Bold className="h-4 w-4" aria-hidden />
      </button>
      <button type="button" onMouseDown={keep} onClick={() => editor.chain().focus().toggleItalic().run()} aria-pressed={st.italic} aria-label="Itálico" title="Itálico (Ctrl+I)" className={btn}>
        <Italic className="h-4 w-4" aria-hidden />
      </button>
      <button type="button" onMouseDown={keep} onClick={() => editor.chain().focus().toggleUnderline().run()} aria-pressed={st.underline} aria-label="Sublinhado" title="Sublinhado (Ctrl+U)" className={btn}>
        <Underline className="h-4 w-4" aria-hidden />
      </button>
      <button type="button" onMouseDown={keep} onClick={() => editor.chain().focus().toggleStrike().run()} aria-pressed={st.strike} aria-label="Tachado" title="Tachado" className={btn}>
        <Strikethrough className="h-4 w-4" aria-hidden />
      </button>
      <span aria-hidden className="mx-1 h-5 w-px bg-white/25" />
      <button
        type="button"
        onMouseDown={keep}
        onClick={() => {
          editor.chain().focus().setTextSelection(editor.state.selection.to).run();
        }}
        aria-label="Cancelar seleção"
        title="Cancelar seleção (Esc)"
        className={btn}
      >
        <X className="h-4 w-4" aria-hidden />
      </button>
    </div>,
    document.body,
  );
}
