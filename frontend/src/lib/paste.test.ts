import { describe, expect, it } from "vitest";
import { parsePastedTable } from "@/lib/paste";

describe("tabela colada", () => {
  it("lê o que o Excel/Sheets copia (tabulação, CRLF, linha final vazia)", () => {
    const t = parsePastedTable("Nome\tCPF\tValor\r\nMaria Souza\t529.982.247-25\t1.200,00\r\nJosé\t111.444.777-35\tR$ 900,00\r\n");
    expect(t.headers).toEqual(["Nome", "CPF", "Valor"]);
    expect(t.rows).toEqual([
      ["Maria Souza", "529.982.247-25", "1.200,00"],
      ["José", "111.444.777-35", "R$ 900,00"],
    ]);
  });

  it("respeita células entre aspas com quebra de linha e aspas internas", () => {
    const t = parsePastedTable('Nome\tEndereço\n"Ana ""Aninha"""\t"Rua A, 10\nApto 2"\n');
    expect(t.rows).toEqual([['Ana "Aninha"', "Rua A, 10\nApto 2"]]);
  });

  it("aceita CSV com ponto e vírgula e completa linhas curtas", () => {
    const t = parsePastedTable("Nome;CPF;Cidade\nAna;529.982.247-25\n");
    expect(t.headers).toEqual(["Nome", "CPF", "Cidade"]);
    expect(t.rows).toEqual([["Ana", "529.982.247-25", ""]]);
  });

  it("ignora linhas e colunas totalmente vazias (sobras da seleção)", () => {
    const t = parsePastedTable("\n\nNome\t\tCPF\t\nAna\t\t1\t\n\t\t\t\n");
    expect(t.headers).toEqual(["Nome", "CPF"]);
    expect(t.rows).toEqual([["Ana", "1"]]);
  });

  it("texto vazio não vira tabela", () => {
    expect(parsePastedTable("   \n ")).toEqual({ headers: [], rows: [] });
  });
});
