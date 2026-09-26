"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Clock, Loader2, XCircle, Ban } from "lucide-react";
import { Badge } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { TERMINAL_STATUSES, type JobOut } from "@/lib/types";

const META: Record<JobOut["status"], { label: string; tone: "neutral" | "primary" | "success" | "warning" | "danger"; icon: React.ReactNode }> = {
  queued: { label: "Aguardando", tone: "neutral", icon: <Clock className="h-3 w-3" aria-hidden /> },
  processing: { label: "Processando", tone: "primary", icon: <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> },
  succeeded: { label: "Concluído", tone: "success", icon: <CheckCircle2 className="h-3 w-3" aria-hidden /> },
  partial: { label: "Concluído parcialmente", tone: "warning", icon: <AlertTriangle className="h-3 w-3" aria-hidden /> },
  failed: { label: "Falhou", tone: "danger", icon: <XCircle className="h-3 w-3" aria-hidden /> },
  cancelled: { label: "Cancelado", tone: "neutral", icon: <Ban className="h-3 w-3" aria-hidden /> },
};

export const isTerminal = (s: string) => TERMINAL_STATUSES.includes(s);

export function JobStatusBadge({ status }: { status: JobOut["status"] }) {
  const m = META[status];
  return (
    <Badge tone={m.tone} icon={m.icon}>
      {m.label}
    </Badge>
  );
}

export const ITEM_LABEL: Record<string, string> = {
  pending: "Aguardando", processing: "Processando", succeeded: "Gerado", failed: "Falhou", skipped: "Ignorada",
};

/** Acompanha um job por polling (1,2 s) até o estado terminal. */
export function useJob(jobId: string | null) {
  return useQuery({
    queryKey: ["job", jobId],
    enabled: !!jobId,
    queryFn: () => api.get<JobOut>(`/jobs/${jobId}`),
    refetchInterval: (q) => (q.state.data && isTerminal(q.state.data.status) ? false : 1200),
    staleTime: 0,
  });
}
