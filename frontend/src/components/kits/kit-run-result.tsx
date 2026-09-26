"use client";

import { useQuery } from "@tanstack/react-query";
import { Download, FileArchive, FileSpreadsheet } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { isTerminal, JobStatusBadge } from "@/components/jobs/job-status";
import { Button } from "@/components/ui/button";
import { Alert, ProgressBar, Spinner } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, downloadFile, errorMessage } from "@/lib/api";
import type { JobFile, KitRunOut } from "@/lib/types";
import { formatBytes, plural } from "@/lib/utils";

/** Acompanha uma geração de kit por polling até todos os documentos membros terminarem. */
export function useKitRun(runId: string | null) {
  return useQuery({
    queryKey: ["kit-run", runId],
    enabled: !!runId,
    queryFn: () => api.get<KitRunOut>(`/kit-runs/${runId}`),
    refetchInterval: (q) => (q.state.data && isTerminal(q.state.data.status) ? false : 1200),
    staleTime: 0,
  });
}

export function KitRunResult({ runId, onClose }: { runId: string; onClose?: () => void }) {
  const q = useKitRun(runId);
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const run = q.data;
  if (!run) return <Spinner label="Iniciando…" />;

  async function dl(f: JobFile) {
    setBusy(f.id);
    try {
      await downloadFile(f.id);
    } catch (e) {
      toast.push({ tone: "danger", title: "Não foi possível baixar", description: errorMessage(e) });
    } finally {
      setBusy(null);
    }
  }

  const done = isTerminal(run.status);
  const finishedMembers = run.members.filter((m) => isTerminal(m.job.status)).length;
  const bundle = (run.files ?? []).find((f) => f.kind === "zip" && !f.expired);
  const report = (run.files ?? []).find((f) => f.kind === "report" && !f.expired);

  return (
    <div className="space-y-4" aria-live="polite" data-testid="kit-run-result" data-status={run.status}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <JobStatusBadge status={run.status} />
        <span className="text-xs text-muted">Kit · {run.kit_name}</span>
      </div>

      <div className="space-y-1.5">
        <ProgressBar
          value={run.total_members ? finishedMembers / run.total_members : 0}
          label="Progresso do kit"
          tone={run.status === "failed" ? "danger" : run.status === "succeeded" ? "success" : "primary"}
        />
        <p className="text-sm text-muted">
          {finishedMembers} de {run.total_members} documentos processados · {plural(run.succeeded_items, "gerado", "gerados")}
          {run.failed_items > 0 && <span className="font-medium text-danger"> · {plural(run.failed_items, "falha", "falhas")}</span>}
        </p>
      </div>
      {!done && <Spinner label="Gerando os documentos do kit…" />}

      {run.status === "failed" && (
        <Alert tone="danger" title="A geração do kit falhou">Nenhum documento foi concluído. Veja os detalhes abaixo.</Alert>
      )}
      {run.status === "partial" && (
        <Alert tone="warning" title="Concluído parcialmente">Alguns documentos não foram gerados — veja a lista e o relatório.</Alert>
      )}

      {done && bundle && (
        <Button className="w-full justify-start" variant="primary" loading={busy === bundle.id} onClick={() => dl(bundle)} data-testid="kit-download-zip">
          <FileArchive className="h-4 w-4" aria-hidden />
          <span className="min-w-0 flex-1 truncate text-left">Baixar tudo (ZIP)</span>
          <span className="text-xs opacity-80">{formatBytes(bundle.size_bytes)}</span>
          <Download className="h-4 w-4" aria-hidden />
        </Button>
      )}

      <ul className="divide-y divide-border rounded-md border border-border">
        {run.members.map((m, i) => {
          const j = m.job;
          const files = (j.files ?? []).filter((f) => !f.expired && f.kind !== "report");
          return (
            <li key={m.generator_id} className="flex flex-wrap items-center justify-between gap-2 p-2.5">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{j.generator_name}</p>
                <JobStatusBadge status={j.status} />
              </div>
              <div className="flex flex-wrap gap-1.5">
                {files.map((f) => (
                  <Button key={f.id} size="sm" loading={busy === f.id} onClick={() => dl(f)} data-testid={`kit-member-${i}-download-${f.kind}`}>
                    {f.kind.toUpperCase()} <Download className="h-3.5 w-3.5" aria-hidden />
                  </Button>
                ))}
                {j.status === "failed" && j.error_message && <span className="text-xs text-danger">{j.error_message}</span>}
              </div>
            </li>
          );
        })}
      </ul>

      {report && (
        <Button size="sm" loading={busy === report.id} onClick={() => dl(report)} data-testid="kit-download-report">
          <FileSpreadsheet className="h-3.5 w-3.5" aria-hidden /> Relatório (CSV)
        </Button>
      )}

      <div className="flex flex-wrap justify-between gap-2 border-t border-border pt-3 text-sm">
        <Link href="/history" className="text-primary underline underline-offset-2">
          Ver no histórico
        </Link>
        {onClose && (
          <Button size="sm" onClick={onClose}>
            {done ? "Fechar" : "Continuar em segundo plano"}
          </Button>
        )}
      </div>
    </div>
  );
}
