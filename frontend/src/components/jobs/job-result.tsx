"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Download, FileArchive, FileSpreadsheet, FileText } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { isTerminal, JobStatusBadge, useJob } from "@/components/jobs/job-status";
import { Button } from "@/components/ui/button";
import { Alert, ProgressBar, Spinner } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, downloadFile, errorMessage } from "@/lib/api";
import type { JobFile, JobItem, Paged } from "@/lib/types";
import { formatBytes, formatDateTime, plural } from "@/lib/utils";

const ICON = { docx: FileText, pdf: FileText, zip: FileArchive, report: FileSpreadsheet } as const;
const LABEL = { docx: "Baixar Word (.docx)", pdf: "Baixar PDF", zip: "Baixar todos os documentos (ZIP)", report: "Baixar relatório por linha (CSV)" } as const;

/** Acompanha um job (polling) e oferece os downloads quando concluir. Pode-se sair da tela: o histórico guarda tudo. */
export function JobResult({ jobId, onClose }: { jobId: string; onClose?: () => void }) {
  const job = useJob(jobId);
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const j = job.data;
  // documento individual que falhou: o motivo está no item (ex.: falha na conversão para PDF), não no job
  const failedItems = useQuery({
    queryKey: ["job-items", jobId, "failed"],
    enabled: !!j && j.kind === "single" && j.status === "failed",
    queryFn: () => api.get<Paged<JobItem>>(`/jobs/${jobId}/items?page_size=5&status=failed`),
  });
  if (!j) return <Spinner label="Iniciando…" />;
  const itemError = failedItems.data?.items.find((i) => i.error_message);

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
  const done = isTerminal(j.status);
  const processed = j.succeeded_items + j.failed_items;
  const files = (j.files ?? []).filter((f) => !f.expired);
  const order = { zip: 0, docx: 1, pdf: 2, report: 3 } as const;

  return (
    <div className="space-y-4" aria-live="polite" data-testid="job-result" data-status={j.status}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <JobStatusBadge status={j.status} />
        <span className="text-xs text-muted">
          {j.kind === "batch" ? "Vários documentos" : "Um documento"} · versão {j.version_number}
        </span>
      </div>

      {j.kind === "batch" && (
        <div className="space-y-1.5">
          <ProgressBar value={j.progress} label="Progresso da geração" tone={j.status === "failed" ? "danger" : j.status === "succeeded" ? "success" : "primary"} />
          <p className="text-sm text-muted">
            {processed} de {j.total_items} processados · {plural(j.succeeded_items, "gerado", "gerados")}
            {j.failed_items > 0 && <span className="font-medium text-danger"> · {plural(j.failed_items, "falha", "falhas")}</span>}
            {j.skipped_items > 0 && ` · ${plural(j.skipped_items, "linha ignorada", "linhas ignoradas")}`}
          </p>
        </div>
      )}
      {!done && <Spinner label={j.status === "queued" ? "Na fila — começa em instantes…" : j.kind === "batch" ? "Gerando documentos…" : "Gerando o documento…"} />}
      {done && j.kind === "single" && j.status === "succeeded" && (
        <p className="flex items-center gap-2 text-base font-semibold text-success">
          <CheckCircle2 className="h-5 w-5" aria-hidden /> Seu documento está pronto.
        </p>
      )}

      {j.status === "failed" && (
        <Alert tone="danger" title={j.kind === "single" ? "Não foi possível gerar o documento" : "A geração falhou"}>
          {j.kind === "single" ? (itemError?.error_message ?? j.error_message ?? "Consulte os detalhes no histórico.") : (j.error_message ?? "Consulte os detalhes no histórico.")}{" "}
          {itemError?.error_code?.startsWith("PDF_") ? "Tente gerar em Word (.docx) — ele não depende da conversão." : "Seus dados não se perderam: tente de novo, ou use “Repetir” no histórico."}
        </Alert>
      )}
      {j.status === "partial" && <Alert tone="warning" title="Parte dos documentos não foi gerada">O relatório (CSV) e o histórico mostram o motivo de cada linha que falhou.</Alert>}

      {done && files.length > 0 && (
        <ul className="space-y-2">
          {[...files].sort((a, b) => order[a.kind] - order[b.kind]).map((f) => {
            const Icon = ICON[f.kind];
            return (
              <li key={f.id}>
                <Button className="w-full justify-start" variant={f.kind === "zip" || (j.kind === "single" && f.kind !== "report") ? "primary" : "secondary"} loading={busy === f.id} onClick={() => dl(f)} data-testid={`download-${f.kind}`}>
                  <Icon className="h-4 w-4" aria-hidden />
                  <span className="min-w-0 flex-1 truncate text-left">{LABEL[f.kind]}</span>
                  <span className="text-xs opacity-80">{formatBytes(f.size_bytes)}</span>
                  <Download className="h-4 w-4" aria-hidden />
                </Button>
              </li>
            );
          })}
        </ul>
      )}
      {done && files.length > 0 && <p className="text-xs text-muted">Os links são temporários e os arquivos ficam disponíveis até {formatDateTime(j.files_expire_at)}.</p>}

      <div className="flex flex-wrap justify-between gap-2 border-t border-border pt-3 text-sm">
        <Link href={`/history/${j.id}`} className="text-primary underline underline-offset-2">
          Ver detalhes no histórico
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
