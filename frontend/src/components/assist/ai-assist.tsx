"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ClipboardPaste, Info, ShieldCheck, Sparkles } from "lucide-react";
import Link from "next/link";
import { useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/form";
import { Alert, Badge } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { displayFor } from "@/lib/fields/masks";
import type { FieldSpec } from "@/lib/fields/normalize";
import type { FieldOut } from "@/lib/types";
import { cn } from "@/lib/utils";

export type AssistStatus = { enabled: boolean; actions_used: number; actions_limit: number };
type FillResult = { values: Record<string, string>; invalid: Record<string, string>; evidence: Record<string, string>; missing: string[]; truncated: boolean };
type Issue = { field: string; label: string; severity: "alta" | "media" | "baixa"; message: string };

export function useAssistStatus() {
  return useQuery({ queryKey: ["assist-status"], queryFn: () => api.get<AssistStatus>("/assist/status"), staleTime: 30_000 });
}

const spec = (f: FieldOut): FieldSpec => ({ name: f.name, label: f.label, type: f.type, required: f.required, default_value: f.default_value, options: f.options, config: f.config, mask: f.mask });

/** Valor vindo da IA (texto pt-BR) → formato que o campo do formulário espera. */
export function toFormValue(f: FieldOut, raw: string): unknown {
  const t = raw.trim();
  if (f.type === "date") {
    const m = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(t);
    return m ? `${m[3]}-${m[2].padStart(2, "0")}-${m[1].padStart(2, "0")}` : t;
  }
  if (f.type === "select") {
    const opt = f.options.find((o) => o.label.toLowerCase() === t.toLowerCase() || o.value === t);
    return opt ? opt.value : t;
  }
  if (f.type === "yes_no") return /^s/i.test(t) ? "Sim" : /^n/i.test(t) ? "Não" : t;
  return displayFor(spec(f), t);
}

function quotaMessage(e: unknown): string {
  if (e instanceof ApiError && e.code === "AI_QUOTA_EXCEEDED") return e.message;
  return errorMessage(e);
}

/** "Cole os dados do cliente": e-mail, WhatsApp ou ficha → campos preenchidos (a pessoa confere antes de gerar). */
export function AiFill({ endpoint, fields, onApply }: { endpoint: string; fields: FieldOut[]; onApply: (values: Record<string, unknown>, invalid: Record<string, string>) => void }) {
  const status = useAssistStatus();
  const toast = useToast();
  const id = useId();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<FillResult | null>(null);

  if (!status.data?.enabled) return null;
  const left = Math.max(0, status.data.actions_limit - status.data.actions_used);

  async function run() {
    setBusy(true);
    try {
      const r = await api.post<FillResult>(endpoint, { text });
      const byName = Object.fromEntries(fields.map((f) => [f.name, f]));
      const values: Record<string, unknown> = {};
      for (const [name, raw] of Object.entries(r.values)) if (byName[name]) values[name] = toFormValue(byName[name], raw);
      onApply(values, r.invalid);
      setLast(r);
      void status.refetch();
      const n = Object.keys(values).length;
      toast.push({
        tone: n ? "success" : "info",
        title: n ? `${n} ${n === 1 ? "campo preenchido" : "campos preenchidos"} pela IA` : "Nenhum dado encontrado no texto",
        description: n ? "Confira cada campo antes de gerar. O que faltou continua em branco." : "Cole um texto que tenha nome, CPF, endereço, valores…",
      });
    } catch (e) {
      toast.push({ tone: "danger", title: "Não foi possível preencher com a IA", description: quotaMessage(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-primary/30 bg-primary-soft p-3" data-testid="ai-fill">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full items-center gap-2 text-left">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-primary text-primary-fg" aria-hidden><Sparkles className="h-4 w-4" /></span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold">Preencher com IA</span>
          <span className="block text-xs text-muted">Cole o e-mail, a mensagem do WhatsApp ou a ficha do cliente: a IA coloca cada dado no campo certo.</span>
        </span>
        <span className="text-xs font-medium text-primary">{open ? "Fechar" : "Abrir"}</span>
      </button>
      {open && (
        <div className="mt-3 space-y-2">
          <label htmlFor={id} className="sr-only">Texto com os dados do cliente</label>
          <Textarea
            id={id}
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={5}
            maxLength={20000}
            placeholder={"Ex.: Oi! Segue meus dados para o contrato: Maria Aparecida Souza, CPF 529.982.247-25, moro na Rua das Acácias, 120, BH. O valor combinado foi R$ 4.500, começando em 10/11."}
            data-testid="ai-fill-text"
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="primary" size="sm" onClick={run} loading={busy} disabled={text.trim().length < 3 || left === 0} data-testid="ai-fill-run">
              <ClipboardPaste className="h-4 w-4" aria-hidden /> Preencher os campos
            </Button>
            <span className="text-xs text-muted">{left} de {status.data.actions_limit} usos de IA restantes este mês</span>
            {left === 0 && <Link href="/assinatura" className="text-xs font-medium text-primary underline">Ver planos</Link>}
          </div>
          {last && (
            <p className="flex items-start gap-1.5 text-xs text-muted" aria-live="polite">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
              {Object.keys(last.values).length} preenchidos
              {Object.keys(last.invalid).length > 0 && `, ${Object.keys(last.invalid).length} com formato a conferir`}
              {last.missing.length > 0 && `, ${last.missing.length} não estavam no texto`}. A IA não inventa: o que não estava no texto fica em branco.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

const SEVERITY: Record<Issue["severity"], { tone: "danger" | "warning" | "neutral"; label: string }> = {
  alta: { tone: "danger", label: "Importante" },
  media: { tone: "warning", label: "Conferir" },
  baixa: { tone: "neutral", label: "Detalhe" },
};

/** "Revisar com IA": lê o documento preenchido e aponta incoerências antes de gerar. Não altera nada sozinha. */
export function AiReview({ generatorId, getValues, onGoToField, disabled }: { generatorId: string; getValues: () => Record<string, unknown>; onGoToField: (name: string) => void; disabled?: boolean }) {
  const status = useAssistStatus();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [issues, setIssues] = useState<Issue[] | null>(null);

  if (!status.data?.enabled) return null;

  async function run() {
    setBusy(true);
    try {
      const r = await api.post<{ issues: Issue[] }>(`/generators/${generatorId}/assist/review`, { values: getValues() });
      setIssues(r.issues);
      void status.refetch();
    } catch (e) {
      toast.push({ tone: "danger", title: "Não foi possível revisar com a IA", description: quotaMessage(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button onClick={run} loading={busy} disabled={disabled || busy} data-testid="ai-review" title="A IA confere datas, nomes, concordância e valores no documento preenchido">
        {!busy && <ShieldCheck className="h-4 w-4" aria-hidden />} Revisar com IA
      </Button>
      <Dialog open={issues !== null} onOpenChange={(o) => !o && setIssues(null)} title="Revisão com IA" description="Apontamentos sobre o documento preenchido. Nada foi alterado: confira e ajuste o que fizer sentido.">
        <div data-testid="ai-review-result">
          {issues && issues.length === 0 ? (
            <Alert tone="success" title="Nada de estranho encontrado">Datas, nomes e valores parecem coerentes. Pode gerar.</Alert>
          ) : (
            <ul className="space-y-2">
              {issues?.map((it, i) => (
                <li key={i} className={cn("rounded-md border p-3 text-sm", it.severity === "alta" ? "border-danger/30 bg-danger-soft" : "border-border bg-surface-2")}>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={SEVERITY[it.severity].tone} icon={it.severity === "alta" ? <AlertTriangle className="h-3 w-3" aria-hidden /> : undefined}>{SEVERITY[it.severity].label}</Badge>
                    {it.label && <span className="font-medium">{it.label}</span>}
                  </div>
                  <p className="mt-1">{it.message}</p>
                  {it.field && (
                    <button type="button" className="mt-1 text-xs font-medium text-primary underline" onClick={() => { setIssues(null); onGoToField(it.field); }}>
                      Ir para o campo
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </Dialog>
    </>
  );
}
