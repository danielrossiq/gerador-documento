// Tabela colada do Excel / Google Sheets / LibreOffice (ou um CSV) → cabeçalho + linhas.

export type PastedTable = { headers: string[]; rows: string[][] };

/**
 * Planilhas copiam como texto separado por tabulação; células com quebra de linha, tabulação ou aspas vêm entre
 * aspas (e aspas internas dobradas). Sem nenhuma tabulação, tenta ";" e depois "," (CSV colado de um arquivo).
 * A primeira linha não vazia é o cabeçalho; linhas totalmente vazias são descartadas.
 */
export function parsePastedTable(text: string): PastedTable {
  const src = text.replace(/\r\n?/g, "\n").replace(/^﻿/, "");
  if (!src.trim()) return { headers: [], rows: [] };
  const firstLine = src.split("\n").find((l) => l.trim()) ?? "";
  const sep = firstLine.includes("\t") ? "\t" : firstLine.includes(";") ? ";" : firstLine.includes(",") ? "," : "\t";

  const records: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  let atCellStart = true;
  for (let i = 0; i < src.length; i++) {
    const ch = src[i];
    if (quoted) {
      if (ch === '"') {
        if (src[i + 1] === '"') {
          cell += '"';
          i++;
        } else quoted = false;
      } else cell += ch;
      continue;
    }
    if (ch === '"' && atCellStart) {
      quoted = true;
      atCellStart = false;
    } else if (ch === sep) {
      row.push(cell);
      cell = "";
      atCellStart = true;
    } else if (ch === "\n") {
      row.push(cell);
      records.push(row);
      row = [];
      cell = "";
      atCellStart = true;
    } else {
      cell += ch;
      atCellStart = false;
    }
  }
  if (cell !== "" || row.length) {
    row.push(cell);
    records.push(row);
  }

  const clean = records.map((r) => r.map((c) => c.trim())).filter((r) => r.some((c) => c !== ""));
  if (!clean.length) return { headers: [], rows: [] };
  const width = Math.max(...clean.map((r) => r.length));
  const pad = (r: string[]) => [...r, ...Array(width - r.length).fill("")];
  const [head, ...body] = clean.map(pad);
  // colunas totalmente vazias (sobras de seleção na planilha) saem
  const keep = head.map((h, i) => h !== "" || body.some((r) => r[i] !== ""));
  const pick = (r: string[]) => r.filter((_, i) => keep[i]);
  return { headers: pick(head), rows: body.map(pick) };
}
