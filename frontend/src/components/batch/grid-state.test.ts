import { describe, expect, it } from "vitest";
import { fillDownEdits, gridReducer, initialState, isBlank, newRow, parseTsv, pasteEdits, toTsv } from "@/components/batch/grid-state";

const row = (v: Record<string, string>) => ({ id: crypto.randomUUID(), v });

describe("parseTsv (colar do Excel/Google Sheets)", () => {
  it("separa linhas e colunas", () => {
    expect(parseTsv("Ana\t529.982.247-25\nBruno\t111.444.777-35\n")).toEqual([["Ana", "529.982.247-25"], ["Bruno", "111.444.777-35"]]);
  });
  it("respeita aspas, tabs e quebras de linha dentro da célula", () => {
    expect(parseTsv('a\t"linha 1\nlinha 2"\t"com ""aspas"""\n')).toEqual([["a", "linha 1\nlinha 2", 'com "aspas"']]);
  });
  it("aceita CRLF e célula vazia no fim", () => {
    expect(parseTsv("a\t\r\nb\tc")).toEqual([["a", ""], ["b", "c"]]);
  });
  it("faz ida e volta com toTsv", () => {
    const m = [["a", "b\nc"], ['d"e', "f\tg"]];
    expect(parseTsv(toTsv(m))).toEqual(m);
  });
});

describe("reducer da grade", () => {
  it("edita células sem mutar o estado anterior e permite desfazer/refazer", () => {
    const s0 = initialState([row({ n: "a" }), row({ n: "b" })]);
    const s1 = gridReducer(s0, { type: "edit", edits: [{ row: 1, name: "n", text: "z" }] });
    expect(s0.rows[1].v.n).toBe("b");
    expect(s1.rows[1].v.n).toBe("z");
    expect(s1.rows[0]).toBe(s0.rows[0]); // compartilhamento estrutural: linha intocada é a mesma referência
    const s2 = gridReducer(s1, { type: "undo" });
    expect(s2.rows[1].v.n).toBe("b");
    expect(gridReducer(s2, { type: "redo" }).rows[1].v.n).toBe("z");
  });

  it("não cria histórico quando nada muda", () => {
    const s0 = initialState([row({ n: "a" })]);
    const s1 = gridReducer(s0, { type: "edit", edits: [{ row: 0, name: "n", text: "a" }] });
    expect(s1).toBe(s0);
  });

  it("cola matriz que ultrapassa o fim criando linhas, respeitando o limite", () => {
    const s0 = initialState([row({}), row({})]);
    const { edits, ensureRows, truncated } = pasteEdits({
      matrix: [["1", "2"], ["3", "4"], ["5", "6"], ["7", "8"]], row0: 1, col0: 0, names: ["a", "b"], rowCount: 2, maxRows: 4, normalize: (_n, t) => t,
    });
    expect(truncated).toBe(true); // linhas 1..3 cabem (limite 4); a 4ª matriz-linha excede
    const s1 = gridReducer(s0, { type: "edit", edits, ensureRows });
    expect(s1.rows).toHaveLength(4);
    expect(s1.rows[3].v).toEqual({ a: "5", b: "6" });
  });

  it("ignora colunas coladas além das existentes", () => {
    const { edits } = pasteEdits({ matrix: [["x", "y", "z"]], row0: 0, col0: 1, names: ["a", "b"], rowCount: 1, maxRows: 10, normalize: (_n, t) => t });
    expect(edits).toEqual([{ row: 0, name: "b", text: "x" }]);
  });

  it("preencher para baixo copia a 1ª linha (ou a linha de cima se só uma estiver selecionada)", () => {
    const rows = [row({ a: "topo" }), row({ a: "" }), row({ a: "" })];
    expect(fillDownEdits(rows, 0, 2, ["a"]).map((e) => e.text)).toEqual(["topo", "topo"]);
    expect(fillDownEdits(rows, 1, 1, ["a"])).toEqual([{ row: 1, name: "a", text: "topo" }]);
  });

  it("adiciona, duplica e remove linhas respeitando o limite e nunca deixando a grade vazia", () => {
    let s = initialState([row({ a: "1" }), row({ a: "2" })]);
    s = gridReducer(s, { type: "duplicate", rows: [0], max: 3 });
    expect(s.rows.map((r) => r.v.a)).toEqual(["1", "1", "2"]);
    s = gridReducer(s, { type: "addRows", count: 5, max: 3 });
    expect(s.rows).toHaveLength(3); // já no limite
    s = gridReducer(s, { type: "remove", rows: [0, 1, 2] });
    expect(s.rows).toHaveLength(1);
    expect(isBlank(s.rows[0])).toBe(true);
  });

  it("importar: 'append' descarta linhas em branco antigas e respeita o máximo", () => {
    const s0 = initialState([row({ a: "x" }), newRow()]);
    const s1 = gridReducer(s0, { type: "append", rows: [row({ a: "y" }), row({ a: "z" })], max: 3 });
    expect(s1.rows.map((r) => r.v.a)).toEqual(["x", "y", "z"]);
  });
});
