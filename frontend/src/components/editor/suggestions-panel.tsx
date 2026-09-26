"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, ChevronDown, Eye, Pencil, RefreshCw, Sparkles, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox, Input, Select } from "@/components/ui/form";
import { Alert, Spinner } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { FIELD_TYPE_LIST, FIELD_TYPE_META } from "@/lib/fields/meta";
import type { FieldOut, FieldType, SuggestionGroup, SuggestionsPayload } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Alta + média. A "alta" sozinha (≥ 0,85) deixava de fora justamente o nome das partes (0,78) — o campo que
 * mais importa num contrato. As de baixa confiança continuam aparecendo, só não entram no "aceitar todas". */
const ACCEPT_ALL_MIN = 0.6;

const SOURCE: Record<string, string> = { rule: "regra", ai: "IA", local: "heurística" };

function ConfidenceDot({ v }: { v: number }) {
  const [label, cls] = v >= 0.85 ? ["alta", "bg-success"] : v >= ACCEPT_ALL_MIN ? ["média", "bg-warning"] : ["baixa", "bg-border-strong"];
  return (
    <span className="inline-flex items-center gap-1" title={`Confiança ${label} (${Math.round(v * 100)}%)`}>
      <span className={cn("h-2 w-2 rounded-full", cls)} aria-hidden />
      <span>confiança {label}</span>
    </span>
  );
}

export function SuggestionsPanel({
  generatorId, analysisStatus, beforeApply, onApplied, onHighlight, onLocate, next,
}: {
  generatorId: string;
  analysisStatus: string;
  beforeApply: () => Promise<boolean>;
  onApplied: (res: { field: FieldOut; applied: number; revision: number } | { revision: number }) => Promise<void> | void;
  onHighlight: (occ: SuggestionGroup["occurrences"] | null) => void;
  onLocate: (occ: SuggestionGroup["occurrences"][number]) => void;
  /** Chamada para o próximo passo (preencher), exibida quando há campos. */
  next?: ReactNode;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [editing, setEditing] = useState<string | null>(null);
  const q = useQuery({
    queryKey: ["suggestions", generatorId],
    queryFn: () => api.get<SuggestionsPayload>(`/generators/${generatorId}/suggestions`),
    refetchInterval: (query) => (["pending", "running"].includes(query.state.data?.analysis.status ?? analysisStatus) ? 1500 : false),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["suggestions", generatorId] });

  const accept = useMutation({
    mutationFn: async (v: { id: string; body: { label?: string; type?: string; apply_to_all: boolean } }) => {
      if (!(await beforeApply())) throw new Error("Salve as alterações pendentes antes de aceitar a sugestão.");
      return api.post<{ field: FieldOut; applied: number; revision: number }>(`/suggestions/${v.id}/accept`, v.body);
    },
    onSuccess: async (res) => {
      await onApplied(res);
      refresh();
      setEditing(null);
      toast.push({ tone: "success", title: `Campo “${res.field.label}” criado`, description: `Aplicado em ${res.applied} ${res.applied === 1 ? "ponto" : "pontos"} do documento.` });
    },
    onError: (e) => toast.push({ tone: "danger", title: "Não foi possível aceitar", description: errorMessage(e) }),
  });
  const ignore = useMutation({
    mutationFn: (id: string) => api.post(`/suggestions/${id}/ignore?apply_to_all=true`),
    onSuccess: () => refresh(),
    onError: (e) => toast.push({ tone: "danger", title: "Não foi possível ignorar", description: errorMessage(e) }),
  });
  const acceptAll = useMutation({
    mutationFn: async () => {
      if (!(await beforeApply())) throw new Error("Salve as alterações pendentes antes de aceitar as sugestões.");
      return api.post<{ accepted_groups: number; revision: number }>(`/generators/${generatorId}/suggestions/accept-all`, { min_confidence: ACCEPT_ALL_MIN });
    },
    onSuccess: async (r) => {
      await onApplied({ revision: r.revision });
      refresh();
      toast.push({ tone: "success", title: r.accepted_groups === 1 ? "1 campo criado" : `${r.accepted_groups} campos criados`, description: "Confira no documento — dá para desfazer excluindo o campo." });
    },
    onError: (e) => toast.push({ tone: "danger", title: "Não foi possível aceitar", description: errorMessage(e) }),
  });
  const reanalyze = useMutation({
    mutationFn: () => api.post(`/generators/${generatorId}/suggestions/analyze`, { force: true }),
    onSuccess: () => {
      refresh();
      toast.push({ tone: "info", title: "Reanálise iniciada" });
    },
  });

  const data = q.data;
  const running = ["pending", "running"].includes(data?.analysis.status ?? analysisStatus);
  const items = data?.items ?? [];
  const confident = items.filter((g) => g.confidence >= ACCEPT_ALL_MIN).length;

  return (
    <div className="space-y-3">
      {items.length > 0 ? (
        <div className="rounded-md bg-primary-soft p-3">
          <p className="text-sm text-fg">
            <Sparkles className="mr-1 inline h-4 w-4 text-primary" aria-hidden />
            Encontramos <strong>{items.length}</strong> {items.length === 1 ? "trecho que parece variar" : "trechos que parecem variar"} de um documento para outro.
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Button size="sm" variant="primary" disabled={confident === 0 || acceptAll.isPending} loading={acceptAll.isPending} onClick={() => acceptAll.mutate()} data-testid="accept-all">
              <Check className="h-4 w-4" aria-hidden /> Aceitar {confident === items.length ? "todas" : "as recomendadas"} ({confident})
            </Button>
            <span className="text-xs text-muted">ou revise uma a uma abaixo</span>
          </div>
        </div>
      ) : (
        next
      )}

      {running && <Spinner label="Analisando o documento…" />}
      {data?.analysis.error && <Alert tone="warning">{data.analysis.error}</Alert>}
      {!running && q.isSuccess && items.length === 0 && (
        <p className="rounded-md border border-dashed border-border-strong p-4 text-center text-sm text-muted">
          Nenhuma sugestão pendente. Para marcar outro trecho, selecione-o no documento e use <strong className="text-fg">Transformar em campo</strong>.
        </p>
      )}

      <ul className="space-y-2" aria-label="Sugestões de campos">
        {items.map((g) => (
          <SuggestionCard
            key={g.id}
            g={g}
            editing={editing === g.id}
            busy={accept.isPending && accept.variables?.id === g.id}
            onEdit={() => setEditing(editing === g.id ? null : g.id)}
            onAccept={(body) => accept.mutate({ id: g.id, body })}
            onIgnore={() => ignore.mutate(g.id)}
            onHighlight={onHighlight}
            onLocate={() => onLocate(g.occurrences[0])}
          />
        ))}
      </ul>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3 text-xs text-muted">
        <span>{data?.analysis.provider === "local" || !data?.analysis.provider ? "Sugestões automáticas por regras" : data.analysis.provider_label}. Nada é aplicado sem a sua confirmação.</span>
        <Button size="sm" variant="ghost" onClick={() => reanalyze.mutate()} disabled={running} loading={reanalyze.isPending}>
          <RefreshCw className="h-3.5 w-3.5" aria-hidden /> Analisar de novo
        </Button>
      </div>
    </div>
  );
}

function SuggestionCard({ g, editing, busy, onEdit, onAccept, onIgnore, onHighlight, onLocate }: {
  g: SuggestionGroup;
  editing: boolean;
  busy: boolean;
  onEdit: () => void;
  onAccept: (b: { label?: string; type?: string; apply_to_all: boolean }) => void;
  onIgnore: () => void;
  onHighlight: (o: SuggestionGroup["occurrences"] | null) => void;
  onLocate: () => void;
}) {
  const [label, setLabel] = useState(g.suggested_label);
  const [type, setType] = useState<FieldType>(g.suggested_type);
  const [all, setAll] = useState(true);
  const meta = FIELD_TYPE_META[g.suggested_type];
  const Icon = meta?.icon;
  const low = g.confidence < ACCEPT_ALL_MIN;
  return (
    <li
      className={cn("rounded-md border bg-surface p-3 text-sm", editing ? "border-primary" : "border-border", low && !editing && "opacity-75")}
      onMouseEnter={() => onHighlight(g.occurrences)}
      onMouseLeave={() => onHighlight(null)}
      onFocus={() => onHighlight(g.occurrences)}
      onBlur={() => onHighlight(null)}
      data-testid="suggestion"
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="break-words">
            <span className="rounded bg-warning-soft px-1 font-medium">{g.text}</span>
            <ArrowRight className="mx-1 inline h-3.5 w-3.5 text-muted" aria-label="vira o campo" />
            <strong>{g.suggested_label}</strong>
          </p>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted">
            {Icon && <span className="inline-flex items-center gap-1"><Icon className="h-3.5 w-3.5" aria-hidden />{meta.label}</span>}
            <ConfidenceDot v={g.confidence} />
            {g.count > 1 && <span>{g.count}× no documento</span>}
          </p>
        </div>
        <Button size="sm" variant="primary" loading={busy} onClick={() => onAccept(editing ? { label, type, apply_to_all: all } : { apply_to_all: true })} aria-label={`Aceitar “${g.text}” como ${g.suggested_label}`}>
          <Check className="h-4 w-4" aria-hidden /> {editing ? "Salvar" : "Aceitar"}
        </Button>
      </div>

      {editing && (
        <div className="mt-3 space-y-2 rounded-md bg-surface-2 p-2">
          <label className="block text-xs font-medium">
            Nome do campo
            <Input className="mt-1 h-9" value={label} onChange={(e) => setLabel(e.target.value)} />
          </label>
          <label className="block text-xs font-medium">
            Tipo
            <Select className="mt-1 h-9" value={type} onChange={(e) => setType(e.target.value as FieldType)}>
              {FIELD_TYPE_LIST.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </Select>
          </label>
          {g.count > 1 && <Checkbox label={`Aplicar às ${g.count} ocorrências`} checked={all} onChange={(e) => setAll(e.target.checked)} />}
          <p className="text-xs text-muted">
            {g.occurrences[0]?.location}{g.count > 1 ? ` e mais ${g.count - 1}` : ""}{g.reason ? ` — ${g.reason}` : ""} · origem: {SOURCE[g.source] ?? g.source}
          </p>
        </div>
      )}

      <div className="mt-2 flex flex-wrap gap-1">
        <Button size="sm" variant="ghost" onClick={onEdit} aria-expanded={editing}>
          {editing ? <ChevronDown className="h-4 w-4 rotate-180" aria-hidden /> : <Pencil className="h-3.5 w-3.5" aria-hidden />} {editing ? "Fechar" : "Ajustar"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onLocate} aria-label={`Ver “${g.text}” no documento`}>
          <Eye className="h-3.5 w-3.5" aria-hidden /> Ver
        </Button>
        <Button size="sm" variant="ghost" className="text-muted" onClick={onIgnore} aria-label={`Ignorar “${g.text}”`}>
          <X className="h-3.5 w-3.5" aria-hidden /> Ignorar
        </Button>
      </div>
    </li>
  );
}
