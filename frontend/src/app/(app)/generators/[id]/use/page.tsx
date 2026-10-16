"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { FileText, Pencil, PencilRuler, RotateCcw, Wand2 } from "lucide-react";
import { useParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";
import { DocPreview } from "@/components/form/doc-preview";
import { FieldInput } from "@/components/form/field-input";
import { GenerateModeTabs, GeneratorHeader, stepHrefs } from "@/components/generators/steps";
import { JobResult } from "@/components/jobs/job-result";
import { AppShell } from "@/components/layout/app-shell";
import { Button, ButtonLink } from "@/components/ui/button";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/form";
import { Alert, Card, EmptyState, ProgressBar, Skeleton } from "@/components/ui/misc";
import { TabPanel, Tabs } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { previewFilename, unknownTokens } from "@/lib/fields/filename";
import { normalizeValue, type FieldSpec } from "@/lib/fields/normalize";
import { exampleValues } from "@/lib/fields/samples";
import type { FieldOut, FormPayload, JobOut } from "@/lib/types";
import { useMediaQuery } from "@/lib/use-media-query";
import { uuid } from "@/lib/utils";

const spec = (f: FieldOut): FieldSpec => ({ name: f.name, label: f.label, type: f.type, required: f.required, default_value: f.default_value, options: f.options, config: f.config, mask: f.mask });

function initialValues(fields: FieldOut[]): Record<string, unknown> {
  const v: Record<string, unknown> = {};
  for (const f of fields) {
    if (f.type === "checkbox") v[f.name] = !!f.default_value;
    else v[f.name] = f.default_value == null ? "" : String(f.default_value);
  }
  return v;
}

const isBlankValue = (v: unknown) => v === undefined || v === null || v === "" || v === false;

function UseForm({ data }: { data: FormPayload }) {
  const toast = useToast();
  const id = data.generator.id;
  const fields = data.fields;
  const storageKey = `minuta:form:${id}`;
  const [pattern, setPattern] = useState(data.generator.filename_pattern);
  const [editName, setEditName] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [busy, setBusy] = useState<"docx" | "pdf" | null>(null);
  const [mobileTab, setMobileTab] = useState("form");
  const [restored, setRestored] = useState(false);
  const [draftAt, setDraftAt] = useState<Date | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const desktop = useMediaQuery("(min-width: 1024px)");
  const idem = useRef<string | null>(null);

  const schema = useMemo(
    () =>
      z.object(
        Object.fromEntries(
          fields.map((f) => [
            f.name,
            z.any().superRefine((v, ctx) => {
              const { error } = normalizeValue(spec(f), v);
              if (error) ctx.addIssue({ code: "custom", message: error });
            }),
          ]),
        ),
      ),
    [fields],
  );
  const form = useForm<Record<string, unknown>>({ resolver: zodResolver(schema), defaultValues: initialValues(fields), mode: "onBlur" });
  const values = form.watch();
  const errors = form.formState.errors;
  const filename = previewFilename(pattern, fields, values, data.generator.name);
  const badTokens = unknownTokens(pattern, fields);

  // ---- rascunho automático neste navegador (os dados não vão para o servidor até gerar)
  useEffect(() => {
    try {
      const saved = localStorage.getItem(storageKey);
      if (saved) {
        form.reset({ ...initialValues(fields), ...JSON.parse(saved) });
        setRestored(true);
      }
    } catch {
      /* armazenamento indisponível: seguimos sem rascunho local */
    }
    const initial = JSON.stringify(initialValues(fields));
    let t: ReturnType<typeof setTimeout> | null = null;
    const sub = form.watch((v) => {
      if (t) clearTimeout(t);
      t = setTimeout(() => {
        try {
          if (JSON.stringify({ ...initialValues(fields), ...v }) === initial) localStorage.removeItem(storageKey);
          else {
            localStorage.setItem(storageKey, JSON.stringify(v));
            setDraftAt(new Date());
          }
        } catch {
          /* cota/privacidade: segue sem persistir */
        }
      }, 700);
    });
    return () => {
      if (t) clearTimeout(t);
      sub.unsubscribe();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function clearForm() {
    try {
      localStorage.removeItem(storageKey);
    } catch {
      /* nada a limpar */
    }
    form.reset(initialValues(fields));
    setRestored(false);
    setDraftAt(null);
    setConfirmClear(false);
    toast.push({ tone: "info", title: "Formulário limpo" });
  }

  function fillExample() {
    const sample = exampleValues(fields, data.doc);
    const current = form.getValues();
    const empty = fields.every((f) => isBlankValue(current[f.name]) || current[f.name] === initialValues([f])[f.name]);
    const next = { ...current };
    let n = 0;
    for (const f of fields) {
      if (!(f.name in sample)) continue;
      if (empty || isBlankValue(current[f.name])) {
        next[f.name] = sample[f.name];
        n++;
      }
    }
    form.reset(next);
    void form.trigger();
    toast.push({ tone: "info", title: n ? `${n} ${n === 1 ? "campo preenchido" : "campos preenchidos"} com exemplo` : "Nada a preencher", description: n ? "Troque pelos dados reais antes de gerar um documento de verdade." : "Todos os campos já têm valor." });
  }

  async function generate(format: "docx" | "pdf") {
    const ok = await form.trigger();
    if (!ok) {
      const first = fields.find((f) => form.formState.errors[f.name]);
      if (first) document.querySelector<HTMLElement>(`[data-testid="field-${first.name}"], [data-testid="field-${first.name}-Sim"]`)?.focus();
      toast.push({ tone: "danger", title: "Corrija os campos destacados", description: "Os erros aparecem embaixo de cada campo." });
      if (!desktop) setMobileTab("form");
      return;
    }
    setBusy(format);
    const key = (idem.current ??= uuid());
    try {
      const job = await api.post<JobOut>(`/generators/${id}/generate`, { values: form.getValues(), format, filename_pattern: pattern }, { headers: { "Idempotency-Key": key } });
      idem.current = null;
      setJobId(job.id);
    } catch (e) {
      if (e instanceof ApiError && e.code === "BATCH_INVALID_ROWS") {
        idem.current = null;
        const fe = (e.details as { invalid_rows?: { field_errors?: Record<string, string> }[] })?.invalid_rows?.[0]?.field_errors ?? {};
        Object.entries(fe).forEach(([name, message]) => form.setError(name, { message }));
        toast.push({ tone: "danger", title: "O servidor encontrou erros nos dados", description: "Corrija os campos destacados e tente de novo." });
      } else {
        // falha de rede: reaproveita a chave na repetição (não duplica o documento se o 1º pedido chegou)
        idem.current = e instanceof ApiError && e.status === 0 ? key : null;
        toast.push({ tone: "danger", title: e instanceof ApiError && e.code === "PDF_CONVERTER_UNAVAILABLE" ? "PDF indisponível" : "Não foi possível gerar", description: `${errorMessage(e)} Seus dados continuam no formulário — é só tentar de novo.` });
      }
    } finally {
      setBusy(null);
    }
  }

  const groups = useMemo(() => {
    const g = new Map<string, FieldOut[]>();
    for (const f of fields) g.set(f.group_name || "Dados do documento", [...(g.get(f.group_name || "Dados do documento") ?? []), f]);
    return [...g.entries()];
  }, [fields]);
  const errorFields = fields.filter((f) => errors[f.name]);
  const requiredFields = fields.filter((f) => f.required);
  const requiredDone = requiredFields.filter((f) => {
    const { value, error } = normalizeValue(spec(f), values[f.name]);
    return !error && !isBlankValue(value);
  }).length;

  if (fields.length === 0) {
    return (
      <EmptyState
        icon={<PencilRuler className="h-9 w-9" aria-hidden />}
        title="Este modelo ainda não tem campos"
        description="Sem campos, o documento gerado seria igual ao original. Marque no documento o que muda (nome, CPF, valor…) e volte aqui."
        action={<ButtonLink href={stepHrefs(id).fields} variant="primary"><PencilRuler className="h-4 w-4" aria-hidden /> Criar campos</ButtonLink>}
      />
    );
  }

  const focusField = (f: FieldOut) => document.querySelector<HTMLElement>(`[data-testid="field-${f.name}"], [data-testid="field-${f.name}-Sim"]`)?.focus();

  const formPanel = (
    <form onSubmit={(e) => e.preventDefault()} noValidate className="space-y-6" aria-label="Formulário do documento">
      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-base font-semibold">Preencha os dados</h2>
          <Button size="sm" variant="ghost" onClick={fillExample} data-testid="fill-example" title="Preenche os campos vazios com valores de exemplo, para ver como o documento fica">
            <Wand2 className="h-4 w-4" aria-hidden /> Preencher com dados de exemplo
          </Button>
        </div>
        {requiredFields.length > 0 && (
          <div className="space-y-1">
            <ProgressBar value={requiredDone / requiredFields.length} label="Campos obrigatórios preenchidos" tone={requiredDone === requiredFields.length ? "success" : "primary"} />
            <p className="text-xs text-muted" aria-live="polite" data-testid="required-progress">
              {requiredDone} de {requiredFields.length} obrigatórios preenchidos <span aria-hidden className="text-danger">*</span>
            </p>
          </div>
        )}
        {restored && (
          <Alert tone="primary" title="Continuando de onde você parou">
            Recuperamos o que você tinha preenchido neste navegador.{" "}
            <button type="button" className="font-medium text-primary underline" onClick={() => setConfirmClear(true)}>Começar do zero</button>
          </Alert>
        )}
      </div>

      {errorFields.length > 0 && (
        <Alert tone="danger" title={`${errorFields.length} ${errorFields.length === 1 ? "campo precisa" : "campos precisam"} de atenção`}>
          <ul className="mt-1 space-y-0.5">
            {errorFields.map((f) => (
              <li key={f.id}>
                <button type="button" className="inline-block min-h-6 py-0.5 text-left underline underline-offset-2" onClick={() => focusField(f)}>
                  {f.label}: {String(errors[f.name]?.message ?? "")}
                </button>
              </li>
            ))}
          </ul>
        </Alert>
      )}
      {groups.map(([group, list]) => (
        <fieldset key={group} className="space-y-4">
          <legend className="mb-1 text-sm font-semibold text-muted">{group}</legend>
          {list.map((f) => (
            <Controller
              key={f.id}
              name={f.name}
              control={form.control}
              render={({ field }) => (
                <FieldInput field={f} value={field.value} onChange={(v) => field.onChange(v)} onBlur={field.onBlur} error={(errors[f.name]?.message as string | undefined) ?? null} />
              )}
            />
          ))}
        </fieldset>
      ))}

      <div className="rounded-md border border-border bg-surface-2 p-3 text-sm">
        {editName ? (
          <Field
            label="Nome do arquivo"
            help={badTokens.length ? undefined : `Resultado: ${filename}.docx · use {código_do_campo} para incluir um valor.`}
            error={badTokens.length ? `Não existe campo com o código ${badTokens.map((b) => `{${b}}`).join(", ")}.` : null}
          >
            {(a) => <Input className="font-mono text-xs" value={pattern} onChange={(e) => setPattern(e.target.value)} {...a} data-testid="filename-pattern" />}
          </Field>
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="min-w-0 break-all">
              <span className="text-muted">Nome do arquivo: </span>
              <span className="font-medium" data-testid="filename-preview">{filename}.docx</span>
            </p>
            <Button size="sm" variant="ghost" onClick={() => setEditName(true)} data-testid="edit-filename">
              <Pencil className="h-3.5 w-3.5" aria-hidden /> Alterar
            </Button>
          </div>
        )}
      </div>

      <div data-sticky-actions className="sticky bottom-0 -mx-4 space-y-2 border-t border-border bg-surface/95 px-4 py-3 backdrop-blur sm:-mx-5 sm:px-5">
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="primary" loading={busy === "docx"} disabled={!!busy} onClick={() => generate("docx")} data-testid="generate-docx">
            <FileText className="h-4 w-4" aria-hidden /> Gerar documento Word
          </Button>
          <Button loading={busy === "pdf"} disabled={!!busy || !data.pdf_available} onClick={() => generate("pdf")} title={data.pdf_available ? undefined : "A conversão para PDF não está disponível neste servidor"} data-testid="generate-pdf">
            <FileText className="h-4 w-4" aria-hidden /> Gerar PDF
          </Button>
          <Button variant="ghost" onClick={() => setConfirmClear(true)} className="ml-auto text-muted">
            <RotateCcw className="h-4 w-4" aria-hidden /> Limpar
          </Button>
        </div>
        <p className="text-xs text-muted" aria-live="polite" data-testid="draft-state">
          {draftAt ? `Rascunho salvo neste navegador às ${draftAt.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}.` : "O que você digita fica salvo neste navegador até você limpar."}
        </p>
        {!data.pdf_available && <p className="text-xs text-warning">PDF indisponível neste servidor (conversor não instalado). O Word funciona normalmente.</p>}
      </div>
    </form>
  );

  const preview = (
    <>
      <p className="mb-2 text-center text-xs text-muted">Prévia atualizada enquanto você digita — em verde o que você preencheu, em amarelo o que falta.</p>
      <DocPreview doc={data.doc} fields={fields} values={values} />
    </>
  );

  return (
    <>
      {desktop ? (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,30rem)_minmax(0,1fr)]">
          <Card className="h-fit p-5">{formPanel}</Card>
          <div tabIndex={0} role="region" aria-label="Prévia do documento (área rolável)" className="doc-canvas sticky top-20 max-h-[calc(100vh-7rem)] overflow-auto rounded-lg p-4">
            {preview}
          </div>
        </div>
      ) : (
        <Tabs value={mobileTab} onValueChange={setMobileTab} tabs={[{ value: "form", label: "Formulário" }, { value: "preview", label: "Prévia" }]} className="mb-4">
          <TabPanel value="form" className="pt-4"><Card className="p-4">{formPanel}</Card></TabPanel>
          <TabPanel value="preview" className="pt-4"><div tabIndex={0} role="region" aria-label="Prévia do documento (área rolável)" className="doc-canvas overflow-x-auto rounded-lg p-2">{preview}</div></TabPanel>
        </Tabs>
      )}

      <Dialog open={!!jobId} onOpenChange={(o) => !o && setJobId(null)} title="Gerando seu documento" size="md">
        {jobId && <JobResult jobId={jobId} onClose={() => setJobId(null)} />}
      </Dialog>
      <ConfirmDialog
        open={confirmClear}
        onOpenChange={setConfirmClear}
        title="Limpar o formulário?"
        description="Tudo o que foi preenchido será apagado deste navegador. Os documentos já gerados continuam no histórico."
        confirmLabel="Limpar formulário"
        danger
        onConfirm={clearForm}
      />
    </>
  );
}

function UseLoader() {
  const { id } = useParams<{ id: string }>();
  const q = useQuery({ queryKey: ["form", id], queryFn: () => api.get<FormPayload>(`/generators/${id}/form`), retry: false, staleTime: 0 });
  const g = q.data?.generator;
  const noDoc = q.error instanceof ApiError && q.error.code === "NOT_FOUND" && /docx/i.test(q.error.message);

  return (
    <AppShell wide>
      {g ? (
        <GeneratorHeader id={id} name={g.name} step="generate" hasTemplate={g.has_template} fieldsCount={q.data!.fields.length} description="Preencha os campos e baixe o documento pronto. A prévia mostra como ele vai ficar.">
          <GenerateModeTabs id={id} current="use" />
        </GeneratorHeader>
      ) : (
        !q.error && <Skeleton className="mb-6 h-24 w-full" />
      )}
      {q.isLoading ? (
        <div className="grid gap-6 lg:grid-cols-2"><Skeleton className="h-96" /><Skeleton className="h-96" /></div>
      ) : q.error ? (
        <div className="space-y-3">
          <Alert tone={noDoc ? "warning" : "danger"} title={noDoc ? "Falta enviar o documento" : "Não foi possível abrir o formulário"}>
            {noDoc ? "Este modelo ainda não tem documento. Envie o documento e marque os campos para poder gerar." : errorMessage(q.error)}
          </Alert>
          <div className="flex flex-wrap gap-2">
            {noDoc ? <ButtonLink href={stepHrefs(id).template} variant="primary">Enviar o documento</ButtonLink> : <Button onClick={() => q.refetch()}>Tentar de novo</Button>}
            <ButtonLink href="/models">Voltar aos modelos</ButtonLink>
          </div>
        </div>
      ) : (
        <UseForm key={id} data={q.data!} />
      )}
    </AppShell>
  );
}

export default function UsePage() {
  return (
    <Suspense>
      <UseLoader />
    </Suspense>
  );
}
