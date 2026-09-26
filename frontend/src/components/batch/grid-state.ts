// Estado puro da grade do lote (sem React): linhas imutáveis, histórico de desfazer/refazer, colar TSV, preencher para baixo.
import { uuid } from "@/lib/utils";

export type Row = { id: string; v: Record<string, string> };
export type GridState = { rows: Row[]; past: Row[][]; future: Row[][] };
export type Edit = { row: number; name: string; text: string };

export type GridAction =
  | { type: "edit"; edits: Edit[]; ensureRows?: number }
  | { type: "addRows"; count: number; after?: number; max: number }
  | { type: "duplicate"; rows: number[]; max: number }
  | { type: "remove"; rows: number[] }
  | { type: "replace"; rows: Row[] }
  | { type: "append"; rows: Row[]; max: number }
  | { type: "undo" }
  | { type: "redo" };

export const HISTORY_LIMIT = 60;
export const newRow = (v: Record<string, string> = {}): Row => ({ id: uuid(), v });
export const isBlank = (r: Row) => Object.values(r.v).every((x) => !x || !x.trim());
export const initialState = (rows: Row[] = [newRow(), newRow(), newRow()]): GridState => ({ rows, past: [], future: [] });

function commit(state: GridState, rows: Row[]): GridState {
  if (rows === state.rows) return state;
  return { rows, past: [...state.past, state.rows].slice(-HISTORY_LIMIT), future: [] };
}

export function gridReducer(state: GridState, a: GridAction): GridState {
  switch (a.type) {
    case "edit": {
      const rows = [...state.rows];
      while (a.ensureRows !== undefined && rows.length < a.ensureRows) rows.push(newRow());
      let changed = rows.length !== state.rows.length;
      const touched = new Map<number, Record<string, string>>();
      for (const e of a.edits) {
        if (e.row < 0 || e.row >= rows.length) continue;
        const base = touched.get(e.row) ?? { ...rows[e.row].v };
        if ((base[e.name] ?? "") !== e.text) {
          base[e.name] = e.text;
          touched.set(e.row, base);
          changed = true;
        } else if (!touched.has(e.row)) touched.set(e.row, base);
      }
      if (!changed) return state;
      for (const [i, v] of touched) rows[i] = { id: rows[i].id, v };
      return commit(state, rows);
    }
    case "addRows": {
      const room = Math.max(0, a.max - state.rows.length);
      const count = Math.min(a.count, room);
      if (count <= 0) return state;
      const rows = [...state.rows];
      const at = a.after === undefined ? rows.length : a.after + 1;
      rows.splice(at, 0, ...Array.from({ length: count }, () => newRow()));
      return commit(state, rows);
    }
    case "duplicate": {
      const idx = [...new Set(a.rows)].sort((x, y) => x - y).filter((i) => i >= 0 && i < state.rows.length);
      if (!idx.length) return state;
      const rows = [...state.rows];
      let offset = 0;
      for (const i of idx) {
        if (rows.length >= a.max) break;
        rows.splice(i + 1 + offset, 0, { id: uuid(), v: { ...state.rows[i].v } });
        offset += 1;
      }
      return commit(state, rows);
    }
    case "remove": {
      const kill = new Set(a.rows);
      let rows = state.rows.filter((_, i) => !kill.has(i));
      if (rows.length === state.rows.length) return state;
      if (rows.length === 0) rows = [newRow()];
      return commit(state, rows);
    }
    case "replace":
      return commit(state, a.rows.length ? a.rows : [newRow()]);
    case "append": {
      const nonBlank = state.rows.filter((r) => !isBlank(r));
      return commit(state, [...nonBlank, ...a.rows].slice(0, a.max));
    }
    case "undo": {
      if (!state.past.length) return state;
      const prev = state.past[state.past.length - 1];
      return { rows: prev, past: state.past.slice(0, -1), future: [state.rows, ...state.future].slice(0, HISTORY_LIMIT) };
    }
    case "redo": {
      if (!state.future.length) return state;
      const [next, ...rest] = state.future;
      return { rows: next, past: [...state.past, state.rows].slice(-HISTORY_LIMIT), future: rest };
    }
  }
}

// ------------------------------------------------------------------ área de transferência (TSV do Excel/Google Sheets)

/** Interpreta TSV com aspas (células com quebra de linha ou tabulação, como o Excel copia). */
export function parseTsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  let i = 0;
  const src = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  while (i < src.length) {
    const ch = src[i];
    if (quoted) {
      if (ch === '"' && src[i + 1] === '"') {
        cell += '"';
        i += 2;
        continue;
      }
      if (ch === '"') {
        quoted = false;
        i++;
        continue;
      }
      cell += ch;
      i++;
      continue;
    }
    if (ch === '"' && cell === "") {
      quoted = true;
      i++;
    } else if (ch === "\t") {
      row.push(cell);
      cell = "";
      i++;
    } else if (ch === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
      i++;
    } else {
      cell += ch;
      i++;
    }
  }
  if (cell !== "" || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}

export function toTsv(matrix: string[][]): string {
  return matrix.map((r) => r.map((c) => (/[\t\n"]/.test(c) ? `"${c.replace(/"/g, '""')}"` : c)).join("\t")).join("\n");
}

/** Transforma a matriz colada em edições a partir de (row0,col0); devolve também quantas linhas novas são necessárias. */
export function pasteEdits(opts: {
  matrix: string[][];
  row0: number;
  col0: number;
  names: string[];
  rowCount: number;
  maxRows: number;
  normalize: (name: string, text: string) => string;
}): { edits: Edit[]; ensureRows: number; truncated: boolean } {
  const { matrix, row0, col0, names, rowCount, maxRows, normalize } = opts;
  const edits: Edit[] = [];
  let truncated = false;
  let maxRow = rowCount;
  matrix.forEach((cells, i) => {
    const r = row0 + i;
    if (r >= maxRows) {
      truncated = true;
      return;
    }
    cells.forEach((text, j) => {
      const name = names[col0 + j];
      if (name === undefined) return;
      edits.push({ row: r, name, text: normalize(name, text) });
    });
    maxRow = Math.max(maxRow, r + 1);
  });
  return { edits, ensureRows: maxRow, truncated };
}

export function fillDownEdits(rows: Row[], r1: number, r2: number, names: string[]): Edit[] {
  const edits: Edit[] = [];
  const source = r1 === r2 && r1 > 0 ? r1 - 1 : r1;
  const from = r1 === r2 ? r1 : r1 + 1;
  for (let r = from; r <= r2; r++) for (const n of names) edits.push({ row: r, name: n, text: rows[source]?.v[n] ?? "" });
  return edits;
}
