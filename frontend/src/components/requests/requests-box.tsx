"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Inbox, XCircle } from "lucide-react";
import { useState } from "react";
import { Button, ButtonLink } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Badge, Card } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { answerHref, shortDate, STATE_LABEL, type ClientRequestOut, type RequestState } from "@/lib/requests";
import { cn } from "@/lib/utils";

const TONE: Record<RequestState, "primary" | "success" | "neutral" | "warning" | "danger"> = {
  open: "warning",
  answered: "success",
  expired: "neutral",
  cancelled: "neutral",
  used: "neutral",
};

/** "Respostas recebidas" (D39): links enviados aos clientes, com o estado de cada um. No Início e na tela Gerar. */
export function RequestsBox({ generatorId, kitId, compact, className }: { generatorId?: string; kitId?: string; compact?: boolean; className?: string }) {
  const toast = useToast();
  const qc = useQueryClient();
  const [cancelId, setCancelId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const params = new URLSearchParams({ page_size: compact ? "5" : "10" });
  if (generatorId) params.set("generator_id", generatorId);
  if (kitId) params.set("kit_id", kitId);
  const q = useQuery({
    queryKey: ["client-requests", generatorId ?? null, kitId ?? null, compact ?? false],
    queryFn: () => api.get<{ items: ClientRequestOut[]; total: number }>(`/client-requests?${params}`),
    refetchInterval: 30_000,
  });
  const items = q.data?.items ?? [];
  if (!q.data || items.length === 0) return null;
  const fresh = items.filter((r) => r.state === "answered" && !r.opened_at).length;

  async function cancel() {
    if (!cancelId) return;
    setBusy(true);
    try {
      await api.post(`/client-requests/${cancelId}/cancel`);
      toast.push({ tone: "info", title: "Link cancelado", description: "Quem tiver o link não consegue mais enviar dados." });
      void qc.invalidateQueries({ queryKey: ["client-requests"] });
      void qc.invalidateQueries({ queryKey: ["client-requests-summary"] });
    } catch (e) {
      toast.push({ tone: "danger", title: "Não foi possível cancelar", description: errorMessage(e) });
    } finally {
      setBusy(false);
      setCancelId(null);
    }
  }

  return (
    <Card className={cn("p-5", className)} data-testid="requests-box">
      <h2 className="flex flex-wrap items-center gap-2 text-lg font-semibold">
        <Inbox className="h-5 w-5 text-primary" aria-hidden /> Respostas recebidas
        {fresh > 0 && <Badge tone="success">{fresh === 1 ? "1 nova" : `${fresh} novas`}</Badge>}
      </h2>
      <ul className="mt-3 divide-y divide-border">
        {items.map((r) => (
          <li key={r.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 py-2.5 text-sm" data-testid="request-row" data-state={r.state}>
            <Badge tone={TONE[r.state]}>{STATE_LABEL[r.state]}</Badge>
            <span className="min-w-0 flex-1">
              {!generatorId && !kitId && <span className="font-medium">{r.target.name} · </span>}
              <span className="text-muted">
                {r.state === "answered" ? `respondido em ${shortDate(r.answered_at)}` : `enviado em ${shortDate(r.created_at)}`}
                {r.state === "open" && ` · vale até ${shortDate(r.expires_at)}`} · {r.fields.length} {r.fields.length === 1 ? "campo" : "campos"}
              </span>
            </span>
            <span className="flex gap-1">
              {r.state === "answered" && r.has_values && (
                <ButtonLink href={answerHref(r)} size="sm" variant={r.opened_at ? "secondary" : "primary"} data-testid="request-open">
                  {r.opened_at ? "Abrir de novo" : "Abrir resposta"}
                </ButtonLink>
              )}
              {(r.state === "open" || r.state === "answered") && (
                <Button size="sm" variant="ghost" onClick={() => setCancelId(r.id)} aria-label={`Cancelar o link de ${r.target.name}`}>
                  <XCircle className="h-4 w-4" aria-hidden /> <span className="sr-only sm:not-sr-only">Cancelar</span>
                </Button>
              )}
            </span>
          </li>
        ))}
      </ul>
      <ConfirmDialog
        open={!!cancelId}
        onOpenChange={(o) => !o && setCancelId(null)}
        title="Cancelar este link?"
        description="O cliente não consegue mais enviar dados por ele. Se já respondeu, a resposta é apagada."
        confirmLabel="Cancelar link"
        danger
        loading={busy}
        onConfirm={cancel}
      />
    </Card>
  );
}
