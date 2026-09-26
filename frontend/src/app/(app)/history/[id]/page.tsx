"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, Download, RotateCw } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { AppShell, PageHeader } from "@/components/layout/app-shell";
import { ITEM_LABEL, isTerminal, JobStatusBadge, useJob } from "@/components/jobs/job-status";
import { JobResult } from "@/components/jobs/job-result";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/form";
import { Alert, Badge, Card, Skeleton } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, downloadFile, errorMessage } from "@/lib/api";
import type { JobItem, JobOut, Paged } from "@/lib/types";
import { formatBytes, formatDateTime, uuid } from "@/lib/utils";

export default function JobDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const toast = useToast();
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const job = useJob(id);
  const j = job.data;
  const items = useQuery({
    queryKey: ["job-items", id, status, page, j?.succeeded_items, j?.failed_items],
    enabled: !!j && j.kind === "batch",
    queryFn: () => api.get<Paged<JobItem>>(`/jobs/${id}/items?page=${page}&page_size=50${status ? `&status=${status}` : ""}`),
  });
  const repeat = useMutation({
    mutationFn: () => api.post<JobOut>(`/jobs/${id}/repeat`, {}, { headers: { "Idempotency-Key": uuid() } }),
    onSuccess: (n) => {
      toast.push({ tone: "success", title: "Nova geração iniciada com os mesmos dados" });
      router.push(`/history/${n.id}`);
    },
    onError: (e) => toast.push({ tone: "danger", title: "Não foi possível repetir", description: errorMessage(e) }),
  });
  const cancel = useMutation({
    mutationFn: () => api.post(`/jobs/${id}/cancel`),
    onSuccess: () => job.refetch(),
    onError: (e) => toast.push({ tone: "danger", title: "Não foi possível cancelar", description: errorMessage(e) }),
  });

  async function dl(fileId: string) {
    try {
      await downloadFile(fileId);
    } catch (e) {
      toast.push({ tone: "danger", title: "Não foi possível baixar", description: errorMessage(e) });
    }
  }

  return (
    <AppShell wide>
      <div className="mb-3">
        <Link href="/history" className="inline-flex items-center gap-1 text-sm text-primary underline underline-offset-2">
          <ArrowLeft className="h-4 w-4" aria-hidden /> Voltar ao histórico
        </Link>
      </div>
      {job.isLoading ? (
        <Skeleton className="h-64" />
      ) : job.error || !j ? (
        <Alert tone="danger" title="Geração não encontrada">{errorMessage(job.error)}</Alert>
      ) : (
        <>
          <PageHeader
            title={j.generator_name}
            description={`${j.kind === "batch" ? "Lote" : "Geração individual"} · versão ${j.version_number} · por ${j.created_by ?? "—"} em ${formatDateTime(j.created_at)}`}
            actions={
              <>
                <JobStatusBadge status={j.status} />
                {!isTerminal(j.status) && <Button onClick={() => cancel.mutate()} loading={cancel.isPending}>Cancelar</Button>}
                {isTerminal(j.status) && j.can_repeat && (
                  <Button onClick={() => repeat.mutate()} loading={repeat.isPending}>
                    <RotateCw className="h-4 w-4" aria-hidden /> Repetir com os mesmos dados
                  </Button>
                )}
              </>
            }
          />
          <div className="grid gap-6 lg:grid-cols-[22rem_minmax(0,1fr)]">
            <Card className="h-fit p-5">
              <h2 className="mb-3 text-sm font-semibold">Resumo e arquivos</h2>
              <JobResult jobId={id} />
              <dl className="mt-4 grid grid-cols-2 gap-2 text-sm">
                <div><dt className="text-xs text-muted">Duração</dt><dd>{j.duration_ms != null ? `${(j.duration_ms / 1000).toFixed(1)} s` : "—"}</dd></div>
                <div><dt className="text-xs text-muted">Tamanho</dt><dd>{formatBytes(j.bytes_total)}</dd></div>
                <div><dt className="text-xs text-muted">Formato</dt><dd>{j.output_format === "both" ? "DOCX + PDF" : j.output_format.toUpperCase()}</dd></div>
                <div><dt className="text-xs text-muted">Arquivos até</dt><dd>{formatDateTime(j.files_expire_at)}</dd></div>
              </dl>
            </Card>

            <div>
              {j.kind === "batch" ? (
                <>
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <h2 className="text-lg font-semibold">Linhas</h2>
                    <Select aria-label="Filtrar linhas por status" className="w-52" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
                      <option value="">Todas</option>
                      <option value="failed">Com falha</option>
                      <option value="skipped">Ignoradas (inválidas)</option>
                      <option value="succeeded">Geradas</option>
                    </Select>
                  </div>
                  <Card className="overflow-x-auto">
                    <table className="w-full min-w-[640px] text-left text-sm">
                      <caption className="sr-only">Linhas do lote</caption>
                      <thead className="border-b border-border bg-surface-2 text-xs uppercase tracking-wide text-muted">
                        <tr><th className="px-4 py-3" scope="col">Linha</th><th className="px-4 py-3" scope="col">Status</th><th className="px-4 py-3" scope="col">Arquivo</th><th className="px-4 py-3" scope="col">Erro</th><th className="px-2 py-3" scope="col"><span className="sr-only">Baixar</span></th></tr>
                      </thead>
                      <tbody>
                        {(items.data?.items ?? []).map((it) => (
                          <tr key={it.id} className="border-b border-border last:border-0">
                            <td className="px-4 py-2 tabular-nums">{it.row_index}</td>
                            <td className="px-4 py-2"><Badge tone={it.status === "succeeded" ? "success" : it.status === "failed" ? "danger" : it.status === "skipped" ? "warning" : "neutral"}>{ITEM_LABEL[it.status]}</Badge></td>
                            <td className="max-w-56 truncate px-4 py-2 text-muted">{it.filename ?? "—"}</td>
                            <td className="px-4 py-2 text-xs">{it.error_message ? <><span className="font-mono text-muted">{it.error_code}</span><br />{it.error_message}</> : "—"}</td>
                            <td className="px-2 py-2">
                              {it.files.filter((f) => !f.expired).map((f) => (
                                <Button key={f.id} size="sm" variant="ghost" onClick={() => dl(f.id)} aria-label={`Baixar ${f.filename}`}><Download className="h-4 w-4" aria-hidden />{f.kind.toUpperCase()}</Button>
                              ))}
                            </td>
                          </tr>
                        ))}
                        {items.data && items.data.items.length === 0 && <tr><td colSpan={5} className="px-4 py-6 text-center text-muted">Nenhuma linha neste filtro.</td></tr>}
                      </tbody>
                    </table>
                  </Card>
                  {items.data && items.data.total > 50 && (
                    <div className="mt-3 flex items-center justify-center gap-3 text-sm">
                      <Button size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Anterior</Button>
                      <span>Página {page} de {Math.ceil(items.data.total / 50)}</span>
                      <Button size="sm" disabled={page * 50 >= items.data.total} onClick={() => setPage((p) => p + 1)}>Próxima</Button>
                    </div>
                  )}
                </>
              ) : (
                <Alert tone="neutral" title="Geração individual">Os arquivos gerados estão no painel ao lado. Eles ficam disponíveis até a data de expiração da política de retenção.</Alert>
              )}
            </div>
          </div>
        </>
      )}
    </AppShell>
  );
}
