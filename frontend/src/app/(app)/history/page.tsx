"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, History as HistoryIcon, Layers, Package, RotateCw } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { AppShell, PageHeader } from "@/components/layout/app-shell";
import { isTerminal, JobStatusBadge } from "@/components/jobs/job-status";
import { Button, ButtonLink } from "@/components/ui/button";
import { Select } from "@/components/ui/form";
import { Badge, Card, EmptyState, Skeleton } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, downloadFile, errorMessage } from "@/lib/api";
import type { JobOut, Paged } from "@/lib/types";
import { formatDateTime, uuid } from "@/lib/utils";

const FORMAT = { docx: "DOCX", pdf: "PDF", both: "DOCX + PDF" } as const;

export default function HistoryPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useToast();
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const q = useQuery({
    queryKey: ["jobs", kind, status, page],
    queryFn: () => api.get<Paged<JobOut>>(`/jobs?page=${page}&page_size=20${kind ? `&kind=${kind}` : ""}${status ? `&status=${status}` : ""}`),
    refetchInterval: (query) => (query.state.data?.items.some((j) => !isTerminal(j.status)) ? 2500 : false),
  });
  const repeat = useMutation({
    mutationFn: (j: JobOut) => api.post<JobOut>(`/jobs/${j.id}/repeat`, {}, { headers: { "Idempotency-Key": uuid() } }),
    onSuccess: (job) => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      toast.push({ tone: "success", title: "Nova geração iniciada com os mesmos dados" });
      router.push(`/history/${job.id}`);
    },
    onError: (e) => toast.push({ tone: "danger", title: "Não foi possível repetir", description: errorMessage(e) }),
  });

  const items = q.data?.items ?? [];
  const totalPages = Math.max(1, Math.ceil((q.data?.total ?? 0) / 20));

  async function quickDownload(j: JobOut) {
    const f = (j.files ?? []).find((x) => !x.expired && (x.kind === "zip" || x.kind === "docx" || x.kind === "pdf"));
    if (!f) return toast.push({ tone: "danger", title: "Arquivos expirados", description: "Repita a geração para obtê-los novamente." });
    try {
      await downloadFile(f.id);
    } catch (e) {
      toast.push({ tone: "danger", title: "Não foi possível baixar", description: errorMessage(e) });
    }
  }

  return (
    <AppShell wide>
      <PageHeader title="Histórico" description="Tudo o que foi gerado: baixe de novo, repita com os mesmos dados ou veja o que deu errado." />
      <div className="mb-4 flex flex-wrap gap-2">
        <Select aria-label="Tipo" value={kind} onChange={(e) => { setKind(e.target.value); setPage(1); }} className="w-44">
          <option value="">Todos os tipos</option>
          <option value="single">Individuais</option>
          <option value="batch">Em lote</option>
          <option value="kit">De kits</option>
        </Select>
        <Select aria-label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} className="w-56">
          <option value="">Todos os status</option>
          <option value="queued">Aguardando</option>
          <option value="processing">Processando</option>
          <option value="succeeded">Concluídos</option>
          <option value="partial">Concluídos parcialmente</option>
          <option value="failed">Com falha</option>
        </Select>
      </div>

      {q.isLoading ? (
        <div className="space-y-2">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-14" />)}</div>
      ) : items.length === 0 ? (
        <EmptyState icon={<HistoryIcon className="h-9 w-9" aria-hidden />} title="Nenhuma geração ainda" description="Quando você gerar documentos — um a um ou em lote — eles aparecem aqui." action={<ButtonLink href="/models" variant="primary">Ir para os modelos</ButtonLink>} />
      ) : (
        <Card className="relative overflow-x-auto">
          <table className="w-full min-w-[1000px] text-left text-sm" data-testid="history-table">
            <caption className="sr-only">Histórico de gerações</caption>
            <thead className="border-b border-border bg-surface-2 text-xs uppercase tracking-wide text-muted">
              <tr>
                <th scope="col" className="px-4 py-3">Documento</th>
                <th scope="col" className="px-4 py-3">Tipo</th>
                <th scope="col" className="px-4 py-3">Usuário</th>
                <th scope="col" className="px-4 py-3">Data e hora</th>
                <th scope="col" className="px-4 py-3 text-right">Docs</th>
                <th scope="col" className="px-4 py-3">Status</th>
                <th scope="col" className="px-4 py-3">Expira em</th>
                <th scope="col" className="px-4 py-3"><span className="sr-only">Ações</span></th>
              </tr>
            </thead>
            <tbody>
              {items.map((j) => (
                <tr key={j.id} className="border-b border-border last:border-0 hover:bg-surface-2/60">
                  <td className="px-4 py-3">
                    <Link href={`/history/${j.id}`} className="font-medium hover:text-primary hover:underline">{j.generator_name}</Link>
                    <p className="text-xs text-muted">{j.kit_name ? `do kit “${j.kit_name}” · ` : ""}v{j.version_number} · {FORMAT[j.output_format]}</p>
                  </td>
                  <td className="px-4 py-3">
                    {j.kit_run_id ? (
                      <Badge tone="primary" icon={<Package className="h-3 w-3" aria-hidden />}>Kit</Badge>
                    ) : j.kind === "batch" ? (
                      <Badge icon={<Layers className="h-3 w-3" aria-hidden />}>Lote</Badge>
                    ) : (
                      <Badge>Individual</Badge>
                    )}
                  </td>
                  <td className="px-4 py-3 text-muted">{j.created_by ?? "—"}</td>
                  <td className="px-4 py-3 text-muted">{formatDateTime(j.created_at)}</td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {j.succeeded_items}/{j.total_items}
                    {(j.failed_items > 0 || j.skipped_items > 0) && <p className="text-xs text-danger">{j.failed_items} falha(s){j.skipped_items ? ` · ${j.skipped_items} ignorada(s)` : ""}</p>}
                  </td>
                  <td className="px-4 py-3"><JobStatusBadge status={j.status} /></td>
                  <td className="px-4 py-3 text-muted">{j.files_expire_at ? formatDateTime(j.files_expire_at) : "—"}</td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-1">
                      <Button size="sm" onClick={() => quickDownload(j)} disabled={!isTerminal(j.status) || !(j.files ?? []).some((f) => !f.expired)} aria-label={`Baixar arquivos de ${j.generator_name}`}>
                        <Download className="h-4 w-4" aria-hidden />
                      </Button>
                      <Button size="sm" onClick={() => repeat.mutate(j)} disabled={!j.can_repeat || !isTerminal(j.status)} loading={repeat.isPending && repeat.variables?.id === j.id} title={j.can_repeat ? "Repetir com os mesmos dados" : "Somente quem gerou (ou o proprietário) pode repetir"} aria-label={`Repetir geração de ${j.generator_name}`}>
                        <RotateCw className="h-4 w-4" aria-hidden />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      {totalPages > 1 && (
        <div className="mt-4 flex items-center justify-center gap-3 text-sm">
          <Button size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Anterior</Button>
          <span>Página {page} de {totalPages}</span>
          <Button size="sm" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>Próxima</Button>
        </div>
      )}
    </AppShell>
  );
}
