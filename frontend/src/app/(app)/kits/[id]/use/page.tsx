"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { FileText, Layers } from "lucide-react";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";
import { FieldInput } from "@/components/form/field-input";
import { KitRunResult } from "@/components/kits/kit-run-result";
import { AppShell, PageHeader } from "@/components/layout/app-shell";
import { KitNav } from "@/components/models/model-nav";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/form";
import { Alert, Badge, Card, Skeleton } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { normalizeValue, type FieldSpec } from "@/lib/fields/normalize";
import type { FieldOut, FieldType, KitFormPayload, KitItemFieldSummary, KitRunOut } from "@/lib/types";
import { uuid } from "@/lib/utils";

const MEMBER_PREFIX = "m__";
const memberKey = (generatorId: string, fieldName: string) => `${MEMBER_PREFIX}${generatorId}__${fieldName}`;

/** Adapta um campo do kit (ou de um documento membro) para o componente genérico de formulário, que espera
 * o formato de `FieldOut` (os campos extras — grupo, inclusão no lote, ocorrências — não têm efeito aqui). */
function toFieldOut(f: { name: string; label: string; type: FieldType; required: boolean } & Partial<FieldOut>): FieldOut {
  return {
    id: f.id ?? f.name, name: f.name, label: f.label, type: f.type, required: f.required,
    description: f.description ?? null, default_value: f.default_value ?? null, example: f.example ?? null,
    mask: f.mask ?? null, group_name: null, position: 0, include_in_batch: true, config: f.config ?? {},
    options: f.options ?? [], occurrences: 1, missing_in_document: false,
  };
}
const toSpec = (f: FieldOut): FieldSpec => ({ name: f.name, label: f.label, type: f.type, required: f.required, default_value: f.default_value, options: f.options, config: f.config, mask: f.mask });

function KitUseForm({ data }: { data: KitFormPayload }) {
  const toast = useToast();
  const kitId = data.kit.id;
  const usableMembers = useMemo(() => data.members.filter((m) => m.usable), [data.members]);
  const [format, setFormat] = useState<"docx" | "pdf" | "both">("docx");
  const [pattern, setPattern] = useState("");
  const [runId, setRunId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const idem = useState(() => uuid())[0];

  // campo do kit → FieldSpec; campo de "só este documento" → FieldSpec com chave prefixada (evita colisão entre documentos)
  const allSpecs = useMemo(() => {
    const specs: { key: string; field: FieldOut }[] = data.fields.map((f) => ({ key: f.name, field: toFieldOut(f) }));
    for (const m of usableMembers) {
      for (const name of m.extra_field_names) {
        const summary = m.fields.find((x: KitItemFieldSummary) => x.name === name);
        if (summary) specs.push({ key: memberKey(m.generator_id, name), field: toFieldOut(summary) });
      }
    }
    return specs;
  }, [data.fields, usableMembers]);

  const schema = useMemo(
    () => z.object(Object.fromEntries(allSpecs.map(({ key, field }) => [key, z.any().superRefine((v, ctx) => {
      const { error } = normalizeValue(toSpec(field), v);
      if (error) ctx.addIssue({ code: "custom", message: error });
    })]))),
    [allSpecs],
  );
  const defaults = useMemo(() => {
    const v: Record<string, unknown> = {};
    for (const { key, field } of allSpecs) v[key] = field.type === "checkbox" ? !!field.default_value : field.default_value == null ? "" : String(field.default_value);
    return v;
  }, [allSpecs]);
  const form = useForm<Record<string, unknown>>({ resolver: zodResolver(schema), defaultValues: defaults, mode: "onBlur" });
  const errors = form.formState.errors;
  const errorCount = Object.keys(errors).length;

  async function generate() {
    const ok = await form.trigger();
    if (!ok) {
      toast.push({ tone: "danger", title: "Corrija os campos destacados", description: "Os erros aparecem ao lado de cada campo." });
      return;
    }
    setBusy(true);
    const values = form.getValues();
    const sharedValues: Record<string, unknown> = {};
    const memberValues: Record<string, Record<string, unknown>> = {};
    for (const { key } of allSpecs) {
      if (key.startsWith(MEMBER_PREFIX)) {
        const [, generatorId, fieldName] = key.split("__");
        (memberValues[generatorId] ??= {})[fieldName] = values[key];
      } else {
        sharedValues[key] = values[key];
      }
    }
    try {
      const run = await api.post<KitRunOut>(
        `/kits/${kitId}/runs`,
        { values: sharedValues, member_values: memberValues, format, filename_pattern: pattern.trim() || null, idempotency_key: idem },
        { headers: { "Idempotency-Key": idem } },
      );
      setRunId(run.id);
    } catch (e) {
      if (e instanceof ApiError && e.code === "KIT_INVALID_VALUES") {
        toast.push({ tone: "danger", title: "O servidor encontrou campos inválidos", description: "Corrija os valores e tente de novo." });
      } else {
        toast.push({ tone: "danger", title: e instanceof ApiError && e.code === "PDF_CONVERTER_UNAVAILABLE" ? "PDF indisponível" : "Não foi possível gerar", description: errorMessage(e) });
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {data.warnings.length > 0 && (
        <Alert tone="warning" className="mb-4" title="Alguns documentos ficaram de fora">
          {data.warnings.join(" ")}
        </Alert>
      )}
      <div className="mx-auto mb-3 flex max-w-2xl flex-wrap items-center gap-2 text-sm" data-testid="kit-outputs">
        <span className="text-muted">Vai gerar:</span>
        {usableMembers.map((m) => (
          <Badge key={m.id} icon={<FileText className="h-3 w-3" aria-hidden />}>{m.generator_name}</Badge>
        ))}
      </div>
      <Card className="mx-auto max-w-2xl p-5">
        <form onSubmit={(e) => e.preventDefault()} noValidate className="space-y-6" aria-label="Formulário do kit">
          {errorCount > 0 && (
            <Alert tone="danger" title={`${errorCount} ${errorCount === 1 ? "campo precisa" : "campos precisam"} de atenção`}>
              Veja as mensagens ao lado de cada campo.
            </Alert>
          )}

          {data.fields.length > 0 && (
            <fieldset className="space-y-4">
              <legend className="mb-1 text-sm font-semibold text-muted">Dados em comum <span className="font-normal">· valem para {usableMembers.length} documentos</span></legend>
              {data.fields.map((f) => (
                <Controller
                  key={f.name}
                  name={f.name}
                  control={form.control}
                  render={({ field }) => (
                    <FieldInput field={toFieldOut(f)} value={field.value} onChange={field.onChange} onBlur={field.onBlur} error={(errors[f.name]?.message as string | undefined) ?? null} />
                  )}
                />
              ))}
            </fieldset>
          )}

          {usableMembers.map((m) => {
            const extra = m.extra_field_names.map((n) => m.fields.find((x) => x.name === n)).filter((x): x is KitItemFieldSummary => !!x);
            if (extra.length === 0) return null;
            return (
              <fieldset key={m.id} className="space-y-4">
                <legend className="mb-1 text-sm font-semibold text-muted">Só em “{m.generator_name}”</legend>
                {extra.map((f) => {
                  const key = memberKey(m.generator_id, f.name);
                  return (
                    <Controller
                      key={key}
                      name={key}
                      control={form.control}
                      render={({ field }) => (
                        <FieldInput field={toFieldOut(f)} value={field.value} onChange={field.onChange} onBlur={field.onBlur} error={(errors[key]?.message as string | undefined) ?? null} />
                      )}
                    />
                  );
                })}
              </fieldset>
            );
          })}

          <fieldset>
            <legend className="mb-1.5 text-sm font-medium">Formato de saída</legend>
            <div className="flex flex-wrap gap-3">
              {([["docx", "DOCX"], ["pdf", "PDF"], ["both", "DOCX e PDF"]] as const).map(([v, t]) => (
                <label key={v} className="flex cursor-pointer items-center gap-2 text-sm">
                  <input type="radio" name="fmt" checked={format === v} onChange={() => setFormat(v)} disabled={v !== "docx" && !data.pdf_available} className="accent-[var(--primary)]" />
                  {t}
                </label>
              ))}
            </div>
            {!data.pdf_available && <p className="mt-1 text-xs text-warning">PDF indisponível neste ambiente (LibreOffice não encontrado).</p>}
          </fieldset>

          <label className="block text-sm font-medium">
            Padrão do nome do arquivo <span className="font-normal text-muted">(opcional — usa o padrão de cada documento se vazio)</span>
            <Input className="mt-1 font-mono text-xs" value={pattern} onChange={(e) => setPattern(e.target.value)} placeholder="Ex.: {modelo}_{nome}_{hoje}" />
          </label>

          <div className="sticky bottom-0 -mx-5 flex flex-wrap gap-2 border-t border-border bg-surface/95 px-5 py-3 backdrop-blur">
            <Button variant="primary" loading={busy} disabled={usableMembers.length === 0} onClick={generate} data-testid="generate-kit">
              <Layers className="h-4 w-4" aria-hidden /> Gerar kit ({usableMembers.length} {usableMembers.length === 1 ? "documento" : "documentos"})
            </Button>
          </div>
        </form>
      </Card>

      <Dialog open={!!runId} onOpenChange={(o) => !o && setRunId(null)} title="Gerando os documentos do kit" size="md">
        {runId && <KitRunResult runId={runId} onClose={() => setRunId(null)} />}
      </Dialog>
    </>
  );
}

function KitUseLoader() {
  const { id } = useParams<{ id: string }>();
  const q = useQuery({ queryKey: ["kit-form", id], queryFn: () => api.get<KitFormPayload>(`/kits/${id}/form`), retry: false, staleTime: 0 });
  const title = q.data?.kit.name ?? "Usar kit";

  return (
    <AppShell wide>
      <PageHeader
        title={title}
        description="Preencha uma vez — cada documento do kit sai pronto com esses dados."
        actions={q.data && <KitNav id={id} current="use" />}
      />
      {q.isLoading ? (
        <Skeleton className="mx-auto h-96 max-w-2xl" />
      ) : q.error ? (
        <Alert tone="danger" title="Não foi possível abrir o kit">{errorMessage(q.error)}</Alert>
      ) : q.data!.members.filter((m) => m.usable).length === 0 ? (
        <Alert tone="warning" title="Nenhum documento pronto">
          <FileText className="mr-1 inline h-4 w-4" aria-hidden /> Adicione ao menos um modelo com documento enviado antes de usar este kit.
        </Alert>
      ) : (
        <KitUseForm data={q.data!} />
      )}
    </AppShell>
  );
}

export default function KitUsePage() {
  return <KitUseLoader />;
}
