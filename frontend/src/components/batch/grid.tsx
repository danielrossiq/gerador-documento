"use client";

import { useVirtualizer } from "@tanstack/react-virtual";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState, type KeyboardEvent as RKeyboardEvent, type MouseEvent as RMouseEvent } from "react";
import { fillDownEdits, pasteEdits, parseTsv, toTsv, type Edit, type GridAction, type Row } from "@/components/batch/grid-state";
import { FIELD_TYPE_META } from "@/lib/fields/meta";
import { displayFor, liveMask } from "@/lib/fields/masks";
import { isoToBr, parseDate, type FieldSpec } from "@/lib/fields/normalize";
import type { FieldType } from "@/lib/types";
import { cn } from "@/lib/utils";

const ROW_H = 36;
const HEAD_H = 56;
const NUM_W = 88;
const WIDTH: Record<FieldType, number> = {
  text_short: 210, text_long: 260, number: 120, currency: 130, date: 140, cpf: 150, cnpj: 180, cep: 110, email: 230, phone: 150, select: 220, yes_no: 100, checkbox: 96,
};

type Sel = { ar: number; ac: number; fr: number; fc: number };
type Editing = { r: number; c: number; seed?: string } | null;
type Move = "down" | "up" | "right" | "left" | "none";

export type GridSpec = FieldSpec & { description?: string | null };
export type GridHandle = {
  scrollToCell: (rowIndex: number, name: string) => boolean;
  selectedRows: () => number[];
  fillDown: () => void;
  focus: () => void;
};

type Props = {
  specs: GridSpec[];
  rows: Row[];
  view: number[];
  errorsFor: (row: Row) => Record<string, string>;
  blank: (row: Row) => boolean;
  dispatch: (a: GridAction) => void;
  maxRows: number;
  onNotice: (msg: string) => void;
  onSelectionChange?: (n: number) => void;
};

export const BatchGrid = forwardRef<GridHandle, Props>(function BatchGrid({ specs, rows, view, errorsFor, blank, dispatch, maxRows, onNotice, onSelectionChange }, ref) {
  const parent = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const [sel, setSel] = useState<Sel>({ ar: 0, ac: 0, fr: 0, fc: 0 });
  const [editing, setEditing] = useState<Editing>(null);
  const [live, setLive] = useState("");
  const names = useMemo(() => specs.map((s) => s.name), [specs]);
  const widths = useMemo(() => specs.map((s) => WIDTH[s.type] ?? 180), [specs]);
  const offsets = useMemo(() => widths.reduce<number[]>((acc, w, i) => [...acc, (acc[i] ?? NUM_W) + w], [NUM_W]), [widths]);
  const totalWidth = offsets[offsets.length - 1] ?? NUM_W;

  const virt = useVirtualizer({ count: view.length, getScrollElement: () => parent.current, estimateSize: () => ROW_H, overscan: 14, scrollPaddingStart: HEAD_H });

  const maxR = Math.max(0, view.length - 1);
  const maxC = Math.max(0, specs.length - 1);
  const clampSel = useCallback((s: Sel): Sel => ({ ar: Math.min(s.ar, maxR), ac: Math.min(s.ac, maxC), fr: Math.min(s.fr, maxR), fc: Math.min(s.fc, maxC) }), [maxR, maxC]);
  const cur = clampSel(sel);
  const r1 = Math.min(cur.ar, cur.fr), r2 = Math.max(cur.ar, cur.fr);
  const c1 = Math.min(cur.ac, cur.fc), c2 = Math.max(cur.ac, cur.fc);

  useEffect(() => onSelectionChange?.(view.length ? r2 - r1 + 1 : 0), [r1, r2, view.length, onSelectionChange]);
  useEffect(() => {
    const up = () => (dragging.current = false);
    window.addEventListener("mouseup", up);
    return () => window.removeEventListener("mouseup", up);
  }, []);

  const rowAt = (vr: number): Row | undefined => rows[view[vr]];
  const cellValue = (vr: number, c: number) => rowAt(vr)?.v[names[c]] ?? "";

  const ensureVisible = useCallback((vr: number, c: number) => {
    virt.scrollToIndex(vr, { align: "auto" });
    const el = parent.current;
    if (!el) return;
    const left = offsets[c], right = left + widths[c];
    if (left < el.scrollLeft + NUM_W) el.scrollLeft = left - NUM_W;
    else if (right > el.scrollLeft + el.clientWidth) el.scrollLeft = right - el.clientWidth;
  }, [virt, offsets, widths]);

  const moveSel = useCallback((dr: number, dc: number, extend: boolean) => {
    setSel((s0) => {
      const s = clampSel(s0);
      const fr = Math.max(0, Math.min(maxR, s.fr + dr));
      const fc = Math.max(0, Math.min(maxC, s.fc + dc));
      ensureVisible(fr, fc);
      return extend ? { ...s, fr, fc } : { ar: fr, ac: fc, fr, fc };
    });
  }, [clampSel, maxR, maxC, ensureVisible]);

  const focusGrid = () => parent.current?.focus({ preventScroll: true });

  // ---------------------------------------------------------------- edição
  const startEdit = (r: number, c: number, seed?: string) => {
    const t = specs[c]?.type;
    if (!rowAt(r) || t === "checkbox") return;
    setSel({ ar: r, ac: c, fr: r, fc: c });
    setEditing({ r, c, seed });
  };
  const commitEdit = (text: string, move: Move) => {
    if (!editing) return;
    const { r, c } = editing;
    const row = view[r];
    if (row !== undefined) dispatch({ type: "edit", edits: [{ row, name: names[c], text: displayFor(specs[c], text) }] });
    setEditing(null);
    focusGrid();
    if (move === "down") moveSel(1, 0, false);
    else if (move === "up") moveSel(-1, 0, false);
    else if (move === "right") moveSel(0, 1, false);
    else if (move === "left") moveSel(0, -1, false);
  };

  // ---------------------------------------------------------------- operações em intervalo
  const rangeEdits = (fn: (r: number, c: number) => string): Edit[] => {
    const out: Edit[] = [];
    for (let r = r1; r <= r2; r++) for (let c = c1; c <= c2; c++) if (view[r] !== undefined) out.push({ row: view[r], name: names[c], text: fn(r, c) });
    return out;
  };
  const clearRange = () => dispatch({ type: "edit", edits: rangeEdits(() => "") });
  const fillDown = useCallback(() => {
    const fullR1 = view[r1], fullR2 = view[r2];
    if (fullR1 === undefined || fullR2 === undefined) return;
    if (view.length !== rows.length && r1 !== r2) onNotice("Com filtro ativo, o preenchimento usa as linhas visíveis.");
    const rowsInView = Array.from({ length: r2 - r1 + 1 }, (_, i) => view[r1 + i]);
    const tmpRows = rowsInView.map((i) => rows[i]);
    const source = r1 === r2 && r1 > 0 ? rows[view[r1 - 1]] : tmpRows[0];
    const edits: Edit[] = [];
    const from = r1 === r2 ? 0 : 1;
    for (let k = from; k < rowsInView.length; k++) for (let c = c1; c <= c2; c++) edits.push({ row: rowsInView[k], name: names[c], text: source?.v[names[c]] ?? "" });
    dispatch({ type: "edit", edits });
    setLive(`${edits.length} células preenchidas`);
    void fillDownEdits;
  }, [view, r1, r2, c1, c2, rows, names, dispatch, onNotice]);

  const copyRange = async (cut: boolean) => {
    const matrix: string[][] = [];
    for (let r = r1; r <= r2; r++) matrix.push(Array.from({ length: c2 - c1 + 1 }, (_, k) => cellValue(r, c1 + k)));
    try {
      await navigator.clipboard.writeText(toTsv(matrix));
      setLive(`${(r2 - r1 + 1) * (c2 - c1 + 1)} células copiadas`);
    } catch {
      onNotice("Não foi possível acessar a área de transferência.");
    }
    if (cut) clearRange();
  };

  const doPaste = (text: string) => {
    const matrix = parseTsv(text).filter((r, i, all) => !(i === all.length - 1 && r.length === 1 && r[0] === ""));
    if (!matrix.length) return;
    const normalize = (name: string, t: string) => displayFor(specs[names.indexOf(name)], t);
    if (matrix.length === 1 && matrix[0].length === 1 && (r2 > r1 || c2 > c1)) {
      dispatch({ type: "edit", edits: rangeEdits(() => displayFor(specs[c1], matrix[0][0])).map((e) => ({ ...e, text: normalize(e.name, matrix[0][0]) })) });
      setLive("Valor aplicado à seleção");
      return;
    }
    const identity = view.length === rows.length;
    const baseRow = view[r1] ?? rows.length;
    const res = pasteEdits({ matrix, row0: identity ? r1 : baseRow, col0: c1, names, rowCount: rows.length, maxRows, normalize });
    let edits = res.edits;
    let ensure = res.ensureRows;
    if (!identity) {
      // com filtro ativo, cada linha colada vai para a linha visível correspondente (as que faltarem são descartadas)
      edits = [];
      ensure = rows.length;
      matrix.forEach((cells, i) => {
        const full = view[r1 + i];
        if (full === undefined) return;
        cells.forEach((t, j) => names[c1 + j] && edits.push({ row: full, name: names[c1 + j], text: normalize(names[c1 + j], t) }));
      });
    }
    dispatch({ type: "edit", edits, ensureRows: ensure });
    if (res.truncated) onNotice(`O limite é de ${maxRows} linhas por lote; o excedente foi descartado.`);
    const rowsPasted = Math.min(matrix.length, maxRows - (identity ? r1 : baseRow));
    setSel({ ar: r1, ac: c1, fr: r1 + rowsPasted - 1, fc: Math.min(maxC, c1 + Math.max(...matrix.map((m) => m.length)) - 1) });
    setLive(`${rowsPasted} linhas coladas`);
  };

  useImperativeHandle(ref, () => ({
    scrollToCell(rowIndex, name) {
      const vr = view.indexOf(rowIndex);
      const c = names.indexOf(name);
      if (vr < 0) return false;
      const col = c < 0 ? 0 : c;
      setEditing(null);
      setSel({ ar: vr, ac: col, fr: vr, fc: col });
      ensureVisible(vr, col);
      focusGrid();
      return true;
    },
    selectedRows: () => Array.from({ length: r2 - r1 + 1 }, (_, i) => view[r1 + i]).filter((x) => x !== undefined),
    fillDown,
    focus: focusGrid,
  }));

  // ---------------------------------------------------------------- teclado
  function onKeyDown(e: RKeyboardEvent<HTMLDivElement>) {
    if (editing) return;
    if ((e.target as HTMLElement).closest("input:not([data-grid-cb]), select, textarea, button")) return;
    const mod = e.ctrlKey || e.metaKey;
    const k = e.key;
    if (mod && k.toLowerCase() === "c") { e.preventDefault(); void copyRange(false); return; }
    if (mod && k.toLowerCase() === "x") { e.preventDefault(); void copyRange(true); return; }
    if (mod && k.toLowerCase() === "d") { e.preventDefault(); fillDown(); return; }
    if (mod && k.toLowerCase() === "z") { e.preventDefault(); dispatch({ type: e.shiftKey ? "redo" : "undo" }); return; }
    if (mod && k.toLowerCase() === "y") { e.preventDefault(); dispatch({ type: "redo" }); return; }
    if (mod && k.toLowerCase() === "a") { e.preventDefault(); setSel({ ar: 0, ac: 0, fr: maxR, fc: maxC }); return; }
    if (mod && k.toLowerCase() === "v") return; // o evento `paste` cuida
    switch (k) {
      case "ArrowDown": e.preventDefault(); moveSel(mod ? maxR : 1, 0, e.shiftKey); return;
      case "ArrowUp": e.preventDefault(); moveSel(mod ? -maxR : -1, 0, e.shiftKey); return;
      case "ArrowRight": e.preventDefault(); moveSel(0, mod ? maxC : 1, e.shiftKey); return;
      case "ArrowLeft": e.preventDefault(); moveSel(0, mod ? -maxC : -1, e.shiftKey); return;
      case "PageDown": e.preventDefault(); moveSel(12, 0, e.shiftKey); return;
      case "PageUp": e.preventDefault(); moveSel(-12, 0, e.shiftKey); return;
      case "Home": e.preventDefault(); moveSel(0, -maxC, e.shiftKey); return;
      case "End": e.preventDefault(); moveSel(0, maxC, e.shiftKey); return;
      case "Tab":
        e.preventDefault();
        if (e.shiftKey) {
          if (cur.ac === 0) moveSel(-1, maxC, false);
          else moveSel(0, -1, false);
        } else if (cur.ac === maxC) moveSel(1, -maxC, false);
        else moveSel(0, 1, false);
        return;
      case "Enter": e.preventDefault(); if (specs[cur.ac]?.type === "checkbox") toggleCheckbox(cur.ar, cur.ac); else startEdit(cur.ar, cur.ac); return;
      case "F2": e.preventDefault(); startEdit(cur.ar, cur.ac); return;
      case "Escape": setSel({ ar: cur.ar, ac: cur.ac, fr: cur.ar, fc: cur.ac }); return;
      case "Delete": case "Backspace": e.preventDefault(); clearRange(); return;
      case " ": if (specs[cur.ac]?.type === "checkbox") { e.preventDefault(); toggleCheckbox(cur.ar, cur.ac); } return;
    }
    if (k.length === 1 && !mod && !e.altKey) { e.preventDefault(); startEdit(cur.ar, cur.ac, k); }
  }

  function toggleCheckbox(vr: number, c: number) {
    const full = view[vr];
    if (full === undefined) return;
    dispatch({ type: "edit", edits: [{ row: full, name: names[c], text: cellValue(vr, c) === "Sim" ? "" : "Sim" }] });
  }

  const onCellMouseDown = (e: RMouseEvent, vr: number, c: number) => {
    if (e.button !== 0 || (e.target as HTMLElement).closest("input, select")) return;
    e.preventDefault();
    focusGrid();
    setEditing(null);
    dragging.current = true;
    setSel((s) => (e.shiftKey ? { ...clampSel(s), fr: vr, fc: c } : { ar: vr, ac: c, fr: vr, fc: c }));
  };
  const onCellEnter = (vr: number, c: number) => {
    if (dragging.current) setSel((s) => ({ ...clampSel(s), fr: vr, fc: c }));
  };

  const activeRow = rowAt(cur.ar);
  const activeId = activeRow ? `gc-${activeRow.id}-${cur.ac}` : undefined;

  return (
    <div className="relative">
      <div
        ref={parent}
        role="grid"
        tabIndex={0}
        aria-label="Planilha do lote: cada linha é um documento e cada coluna é um campo"
        aria-rowcount={view.length + 1}
        aria-colcount={specs.length + 1}
        aria-multiselectable="true"
        aria-activedescendant={activeId}
        onKeyDown={onKeyDown}
        onPaste={(e) => {
          if (editing) return;
          const t = e.clipboardData.getData("text/plain");
          if (t) {
            e.preventDefault();
            doPaste(t);
          }
        }}
        onCopy={(e) => {
          if (editing) return;
          e.preventDefault();
          const m: string[][] = [];
          for (let r = r1; r <= r2; r++) m.push(Array.from({ length: c2 - c1 + 1 }, (_, k) => cellValue(r, c1 + k)));
          e.clipboardData.setData("text/plain", toTsv(m));
        }}
        className="h-[calc(100vh-19rem)] min-h-80 overflow-auto rounded-lg border border-border-strong bg-surface outline-offset-2"
        data-testid="batch-grid"
      >
        <div style={{ width: totalWidth, height: HEAD_H + virt.getTotalSize(), position: "relative" }}>
          <div role="row" aria-rowindex={1} className="sticky top-0 z-20 flex border-b border-border-strong bg-surface-2" style={{ height: HEAD_H, width: totalWidth }}>
            <div role="columnheader" aria-colindex={1} className="sticky left-0 z-30 flex items-center border-r border-border-strong bg-surface-2 px-2 text-xs font-semibold text-muted" style={{ width: NUM_W }}>
              Linha
            </div>
            {specs.map((s, c) => {
              const Icon = FIELD_TYPE_META[s.type]?.icon;
              return (
                <div key={s.name} role="columnheader" aria-colindex={c + 2} title={s.description ?? undefined} className="flex flex-col justify-center gap-0.5 border-r border-border px-2" style={{ width: widths[c] }}
                  onClick={() => { setSel({ ar: 0, ac: c, fr: maxR, fc: c }); focusGrid(); }}>
                  <span className="truncate text-sm font-semibold">
                    {s.label}
                    {s.required && (<><span aria-hidden className="text-danger"> *</span><span className="sr-only"> (obrigatório)</span></>)}
                  </span>
                  <span className="flex items-center gap-1 truncate text-[11px] text-muted">
                    {Icon && <Icon className="h-3 w-3" aria-hidden />}
                    {FIELD_TYPE_META[s.type]?.label}
                  </span>
                </div>
              );
            })}
          </div>

          {virt.getVirtualItems().map((vi) => {
            const row = rowAt(vi.index);
            if (!row) return null;
            const errs = errorsFor(row);
            const nErr = Object.keys(errs).length;
            const isBlank = blank(row);
            const inRows = vi.index >= r1 && vi.index <= r2;
            return (
              <div key={row.id} role="row" aria-rowindex={vi.index + 2} style={{ position: "absolute", top: HEAD_H + vi.start, left: 0, height: ROW_H, width: totalWidth, display: "flex" }} className={cn(vi.index % 2 ? "bg-surface-2/40" : "bg-surface")}>
                <div
                  role="rowheader" aria-colindex={1}
                  onClick={() => { setSel({ ar: vi.index, ac: 0, fr: vi.index, fc: maxC }); focusGrid(); }}
                  className={cn("sticky left-0 z-10 flex cursor-pointer items-center gap-1.5 border-b border-r border-border-strong px-2 text-xs tabular-nums", inRows ? "bg-primary-soft font-semibold" : "bg-surface-2")}
                  style={{ width: NUM_W }}
                >
                  <span className="w-8 text-right">{view[vi.index] + 1}</span>
                  {isBlank ? null : nErr ? (
                    <span className="inline-flex items-center gap-0.5 text-danger" title={`${nErr} erro(s) nesta linha`}><AlertTriangle className="h-3.5 w-3.5" aria-hidden /><span className="sr-only">{nErr} erros</span></span>
                  ) : (
                    <span className="text-success" title="Linha válida"><CheckCircle2 className="h-3.5 w-3.5" aria-hidden /><span className="sr-only">válida</span></span>
                  )}
                </div>
                {specs.map((s, c) => {
                  const err = isBlank ? undefined : errs[s.name];
                  const isActive = vi.index === cur.ar && c === cur.ac;
                  const isSel = inRows && c >= c1 && c <= c2;
                  const isEd = editing?.r === vi.index && editing.c === c;
                  const value = row.v[s.name] ?? "";
                  return (
                    <div
                      key={s.name} id={`gc-${row.id}-${c}`} role="gridcell" aria-colindex={c + 2} aria-selected={isSel} aria-invalid={err ? true : undefined}
                      data-active={isActive || undefined} data-selected={isSel || undefined} data-testid={`cell-${vi.index}-${s.name}`}
                      title={err}
                      onMouseDown={(e) => onCellMouseDown(e, vi.index, c)} onMouseEnter={() => onCellEnter(vi.index, c)} onDoubleClick={() => startEdit(vi.index, c)}
                      className="grid-cell relative flex select-none items-center overflow-hidden px-2 text-sm" style={{ width: widths[c] }}
                    >
                      {isEd ? (
                        <CellEditor spec={s} initial={value} seed={editing?.seed} onCommit={commitEdit} onCancel={() => { setEditing(null); focusGrid(); }} />
                      ) : s.type === "checkbox" ? (
                        <input type="checkbox" data-grid-cb tabIndex={-1} aria-label={`${s.label}, linha ${view[vi.index] + 1}`} checked={value === "Sim"} onChange={() => toggleCheckbox(vi.index, c)} onClick={focusGrid} className="h-4 w-4 accent-[var(--primary)]" />
                      ) : (
                        <span className="truncate">{value}</span>
                      )}
                      {err && !isEd && (<><span aria-hidden className="ml-auto pl-1 text-xs font-bold text-danger">⚠</span><span className="sr-only">Erro: {err}</span></>)}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
        {view.length === 0 && <p className="absolute inset-x-0 top-24 text-center text-sm text-muted">Nenhuma linha corresponde ao filtro.</p>}
      </div>
      <div className="sr-only" role="status" aria-live="polite">{live}</div>
    </div>
  );
});

function CellEditor({ spec, initial, seed, onCommit, onCancel }: { spec: GridSpec; initial: string; seed?: string; onCommit: (t: string, m: Move) => void; onCancel: () => void }) {
  const [text, setText] = useState(seed !== undefined ? liveMask(spec.type, seed) : initial);
  const ref = useRef<HTMLElement | null>(null);
  const setRef = (el: HTMLElement | null) => {
    ref.current = el;
  };
  const done = useRef(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.focus();
    if (el instanceof HTMLInputElement && el.type === "text") {
      if (seed !== undefined) el.setSelectionRange(el.value.length, el.value.length);
      else el.select();
    }
  }, [seed]);
  const finish = (move: Move, save = true) => {
    if (done.current) return;
    done.current = true;
    if (save) onCommit(text, move);
    else onCancel();
  };
  const onKey = (e: RKeyboardEvent) => {
    e.stopPropagation();
    if (e.key === "Enter") { e.preventDefault(); finish(e.shiftKey ? "up" : "down"); }
    else if (e.key === "Tab") { e.preventDefault(); finish(e.shiftKey ? "left" : "right"); }
    else if (e.key === "Escape") { e.preventDefault(); finish("none", false); }
  };
  const cls = "h-full w-full min-w-0 bg-transparent outline-none";
  const label = `Editar ${spec.label}`;
  if (spec.type === "select" || spec.type === "yes_no") {
    const opts = spec.type === "yes_no" ? ["Sim", "Não"] : spec.options.map((o) => o.label);
    return (
      <select ref={setRef} aria-label={label} className={cls} value={opts.includes(text) ? text : ""} onChange={(e) => setText(e.target.value)} onKeyDown={onKey} onBlur={() => finish("none")}>
        <option value=""></option>
        {opts.map((o) => (<option key={o} value={o}>{o}</option>))}
      </select>
    );
  }
  if (spec.type === "date") {
    return (
      <input ref={setRef} type="date" aria-label={label} className={cls} value={parseDate(text) ?? ""} onChange={(e) => setText(e.target.value ? isoToBr(e.target.value) : "")} onKeyDown={onKey} onBlur={() => finish("none")} />
    );
  }
  return (
    <input ref={setRef} type="text" aria-label={label} className={cls} value={text} inputMode={spec.type === "number" || spec.type === "currency" ? "decimal" : undefined}
      onChange={(e) => setText(liveMask(spec.type, e.target.value))} onKeyDown={onKey} onBlur={() => finish("none")} />
  );
}
