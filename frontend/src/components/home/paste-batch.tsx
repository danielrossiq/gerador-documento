"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, CircleHelp, ClipboardPaste, Eraser, Layers, Search, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { useMe } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Select, Textarea } from "@/components/ui/form";
import { Alert, Spinner } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { putIncomingBatch } from "@/lib/batch-handoff";
import { parsePastedTable } from "@/lib/paste";
import type { GeneratorOut, IdentifyCandidate, IdentifyMatch, IdentifyResult } from "@/lib/types";
import { cn, plural } from "@/lib/utils";

const SOURCE_LABEL: Record<IdentifyMatch["source"], string> = {
  nome: "mesmo nome do campo",
  parecido: "nome parecido",
  conteudo: "reconhecido pelo conteúdo",
  semantico: "sugestão da IA — confira",
};
const PREVIEW_ROWS = 5;

/**
 * "Cole aqui e a gente descobre o modelo": a pessoa cola as linhas de uma planilha (com os títulos), o servidor
 * compara as colunas com os campos de todos os modelos e a tela mostra qual deles usar — e como cada coluna
 * vira um campo — antes de levar as linhas para a tela de lote.
 */
export function PasteBatch({ models }: { models: GeneratorOut[] }) {
  const router = useRouter();
  const toast = useToast();
  const maxRows = useMe().data?.limits?.max_batch_rows ?? 1000;
  const [text, setText] = useState("");
  const [chosen, setChosen] = useState<string | null>(null); // modelo escolhido na mão
  const [pick, setPick] = useState(0);
  const table = useMemo(() => parsePastedTable(text), [text]);
  const ready = table.headers.length > 0 && table.rows.length > 0;

  const payload = useMemo(
    () => ({
      headers: table.headers.slice(0, 100).map((h) => h.slice(0, 200)),
      rows: table.rows.slice(0, 30).map((r) => r.slice(0, 100).map((c) => c.slice(0, 1000))),
      ...(chosen ? { generator_id: chosen } : {}),
    }),
    [table, chosen],
  );
  const ident = useQuery({
    queryKey: ["identify", payload],
    enabled: ready,
    staleTime: Infinity,
    queryFn: () => api.post<IdentifyResult>("/batch/identify", payload),
  });

  const result = ident.data;
  const candidates = result?.candidates ?? [];
  const cand: IdentifyCandidate | undefined = candidates[Math.min(pick, Math.max(0, candidates.length - 1))];
  const byColumn = new Map((cand?.mapping ?? []).map((m) => [m.column, m]));

  function reset() {
    setText("");
    setChosen(null);
    setPick(0);
  }

  function go(c: IdentifyCandidate) {
    const rows = table.rows.map((r) => Object.fromEntries(c.mapping.map((m) => [m.field, r[m.column] ?? ""])));
    if (!putIncomingBatch(c.generator_id, { rows, ignored: c.unmatched_columns })) {
      toast.push({ tone: "danger", title: "Não foi possível levar as linhas", description: "O navegador bloqueou o armazenamento temporário. Cole direto na tela de lote do modelo." });
      return;
    }
    router.push(`/generators/${c.generator_id}/batch?colado=1`);
  }

  if (!ready) {
    return (
      <div>
        <label htmlFor="paste-area" className="sr-only">Cole aqui as linhas da planilha, com a linha de títulos</label>
        <Textarea
          id="paste-area"
          data-testid="paste-area"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={6}
          spellCheck={false}
          placeholder="Clique aqui e cole (Ctrl+V) as linhas copiadas do Excel ou do Google Planilhas — com a linha de títulos no topo."
          className="paste-grid min-h-40 resize-y font-mono text-xs leading-6"
        />
        {text.trim() && table.headers.length > 0 && table.rows.length === 0 && (
          <p className="mt-2 text-sm text-warning" role="status">Colou só uma linha. Inclua a linha de títulos e pelo menos uma linha de dados.</p>
        )}
        <p className="mt-2 flex items-start gap-1.5 text-xs text-muted">
          <CircleHelp className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /> Os títulos das colunas são comparados com os campos dos seus modelos (nome, grafia parecida e o próprio conteúdo: CPF, CNPJ, datas…).
        </p>
      </div>
    );
  }

  const total = table.rows.length;
  const tooMany = total > maxRows;

  return (
    <div className="space-y-3" data-testid="paste-result">
      <div aria-live="polite">
        {ident.isLoading ? (
          <Spinner label="Procurando o modelo que usa essas colunas…" />
        ) : ident.error ? (
          <Alert tone="danger" title="Não foi possível identificar o modelo">{errorMessage(ident.error)}</Alert>
        ) : !cand ? (
          <Alert tone="warning" title="Não encontramos um modelo para essas colunas">
            Os títulos precisam lembrar os nomes dos campos (ex.: “Nome do contratante”, “CPF”). Escolha o modelo abaixo ou baixe a planilha-modelo dele na tela de lote.
          </Alert>
        ) : cand.exact ? (
          <Alert tone="success" title={`Encontramos o modelo: ${cand.name}`}>
            <span data-testid="identify-status" data-status="exact">Todas as {plural(table.headers.length, "coluna corresponde", "colunas correspondem")} a campos dele.</span>
          </Alert>
        ) : (
          <Alert tone={result?.status === "probable" || chosen ? "primary" : "warning"} title={chosen ? `Modelo escolhido: ${cand.name}` : `Parece ser o modelo: ${cand.name}`}>
            <span data-testid="identify-status" data-status={result?.status}>
              {plural(cand.mapping.length, "coluna reconhecida", "colunas reconhecidas")} de {table.headers.length}
              {cand.unmatched_columns.length > 0 && <> · {plural(cand.unmatched_columns.length, "fica de fora", "ficam de fora")}: {cand.unmatched_columns.join(", ")}</>}
              {cand.missing_required.length > 0 && <> · sem coluna para: <strong>{cand.missing_required.join(", ")}</strong> (dá para completar na tela do lote)</>}
              {result?.semantic && cand.mapping.some((m) => m.source === "semantico") && <> · <Sparkles className="inline h-3.5 w-3.5" aria-hidden /> parte das correspondências veio da IA</>}
            </span>
          </Alert>
        )}
      </div>

      {candidates.length > 1 && !chosen && (
        <div className="flex flex-wrap items-center gap-2 text-sm" role="radiogroup" aria-label="Outros modelos possíveis">
          <span className="text-muted">Outros possíveis:</span>
          {candidates.map((c, i) => (
            <button
              key={c.generator_id}
              type="button"
              role="radio"
              aria-checked={i === pick}
              onClick={() => setPick(i)}
              className={cn("rounded-full border px-3 py-1 text-xs font-medium", i === pick ? "border-primary bg-primary-soft text-primary" : "border-border text-muted hover:text-fg")}
            >
              {c.name} · {Math.round(c.score * 100)}%
            </button>
          ))}
        </div>
      )}

      <div className="overflow-x-auto rounded-md border border-border" data-testid="paste-preview">
        <table className="w-full text-left text-xs">
          <thead className="bg-surface-2">
            <tr>
              {table.headers.map((h, i) => {
                const m = byColumn.get(i);
                return (
                  <th key={i} scope="col" className="min-w-32 border-b border-border px-2 py-1.5 align-top font-semibold">
                    <span className="block truncate" title={h}>{h || <em className="font-normal text-muted">(sem título)</em>}</span>
                    {m ? (
                      <span className={cn("mt-0.5 flex items-center gap-1 font-normal", m.source === "semantico" ? "text-warning" : "text-success")} title={SOURCE_LABEL[m.source]}>
                        {m.source === "semantico" ? <Sparkles className="h-3 w-3 shrink-0" aria-hidden /> : <CheckCircle2 className="h-3 w-3 shrink-0" aria-hidden />}
                        <span className="truncate">{m.label}</span>
                        <span className="sr-only"> ({SOURCE_LABEL[m.source]})</span>
                      </span>
                    ) : (
                      <span className="mt-0.5 block font-normal text-muted">{cand ? "não usada" : "—"}</span>
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {table.rows.slice(0, PREVIEW_ROWS).map((r, ri) => (
              <tr key={ri} className="border-b border-border last:border-0">
                {table.headers.map((_, ci) => (
                  <td key={ci} className={cn("max-w-48 truncate px-2 py-1", !byColumn.has(ci) && cand && "text-muted")}>{r[ci]}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {total > PREVIEW_ROWS && <p className="border-t border-border bg-surface-2 px-2 py-1 text-xs text-muted">+ {plural(total - PREVIEW_ROWS, "linha", "linhas")}</p>}
      </div>
      {tooMany && <p className="text-sm text-warning">Um lote aceita até {maxRows} linhas; as demais ficam de fora.</p>}

      <div className="flex flex-wrap items-center gap-2">
        {cand && (
          <Button variant="primary" onClick={() => go(cand)} data-testid="paste-go">
            <Layers className="h-4 w-4" aria-hidden /> Gerar {plural(Math.min(total, maxRows), "documento", "documentos")} com {cand.name}
            <ArrowRight className="h-4 w-4" aria-hidden />
          </Button>
        )}
        <label className="flex items-center gap-2 text-sm text-muted">
          <Search className="h-4 w-4" aria-hidden />
          <span className="sr-only sm:not-sr-only">{cand ? "Outro modelo:" : "Escolher o modelo:"}</span>
          <Select
            aria-label="Escolher o modelo manualmente"
            value={chosen ?? ""}
            onChange={(e) => {
              setChosen(e.target.value || null);
              setPick(0);
            }}
            className="w-56"
          >
            <option value="">{chosen ? "Voltar à identificação automática" : "Selecione…"}</option>
            {models.map((g) => (
              <option key={g.id} value={g.id}>{g.name}</option>
            ))}
          </Select>
        </label>
        <Button variant="ghost" onClick={reset} className="ml-auto">
          <Eraser className="h-4 w-4" aria-hidden /> Colar outra tabela
        </Button>
      </div>
    </div>
  );
}

export function PasteBatchTitle() {
  return (
    <span className="flex items-center gap-2">
      <ClipboardPaste className="h-5 w-5 text-primary" aria-hidden /> Gerar em lote colando uma planilha
    </span>
  );
}

