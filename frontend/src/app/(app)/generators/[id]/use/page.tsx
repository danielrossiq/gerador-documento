"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { FileText, Save } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";
import { AppShell, PageHeader } from "@/components/layout/app-shell";
import { DocPreview } from "@/components/form/doc-preview";
import { FieldInput } from "@/components/form/field-input";
import { JobResult } from "@/components/jobs/job-result";
import { ModelNav } from "@/components/models/model-nav";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/form";
import { Alert, Card, Skeleton } from "@/components/ui/misc";
import { TabPanel, Tabs } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { formatValue, normalizeValue, type FieldSpec } from "@/lib/fields/normalize";
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

/** Nome de arquivo previsto (mesma ideia do servidor; o servidor garante unicidade e sanitiza de verdade). */
function previewFilename(pattern: string, fields: FieldOut[], values: Record<string, unknown>, generator: string): string {
  const tokens: Record<string, string> = { hoje: new Date().toISOString().slice(0, 10), linha: "0001", gerador: generator };
  for (const f of fields) {
    const { value, error } = normalizeValue({ ...spec(f), required: false }, values[f.name]);
    tokens[f.name] = error ? "" : formatValue(spec(f), value);
  }
  tokens.data ??= tokens.hoje;
  const raw = pattern.replace(/\{([a-z][a-z0-9_]*)\}/g, (_, k: string) => tokens[k] ?? "");
  return raw.replace(/[\\/:*?"<>|\x00-\x1f]/g, "-").replace(/\s+/g, "_").replace(/^[\s._-]+|[\s._-]+$/g, "") || "documento";
}

function UseForm({ data }: { data: FormPayload }) {
  const toast = useToast();
  const id = data.generator.id;
  const fields = data.fields;
  const storageKey = `minuta:form:${id}`;
  const [pattern, setPattern] = useState(data.generator.filename_pattern);
  const [jobId, setJobId] = useState<string | null>(null);
  const [busy, setBusy] = useState<"docx" | "pdf" | null>(null);
  const [mobileTab, setMobileTab] = useState("form");
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

  useEffect(() => {
    try {
      const saved = localStorage.getItem(storageKey);
      if (saved) {
        form.reset({ ...initialValues(fields), ...JSON.parse(saved) });
        toast.push({ tone: "info", title: "Rascunho restaurado", description: "Recuperamos os dados que você salvou neste navegador." });
      }
    } catch {
      /* armazenamento indisponível: seguimos sem rascunho local */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function saveDraft() {
    try {
      localStorage.setItem(storageKey, JSON.stringify(form.getValues()));
      toast.push({ tone: "success", title: "Rascunho salvo neste navegador" });
    } catch {
      toast.push({ tone: "danger", title: "Não foi possível salvar o rascunho" });
    }
  }
  function clearDraft() {
    localStorage.removeItem(storageKey);
    form.reset(initialValues(fields));
  }

  async function generate(format: "docx" | "pdf") {
    const ok = await form.trigger();
    if (!ok) {
      const first = fields.find((f) => form.formState.errors[f.name]);
      if (first) document.querySelector<HTMLElement>(`[data-testid="field-${first.name}"]`)?.focus();
      toast.push({ tone: "danger", title: "Corrija os campos destacados", description: "Os erros aparecem ao lado de cada campo." });
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
        toast.push({ tone: "danger", title: "O servidor encontrou erros nos dados", description: "Corrija os campos destacados." });
      } else {
        if (!(e instanceof ApiError) || e.status >= 400) idem.current = e instanceof ApiError && e.status === 0 ? key : null; // rede: reaproveita a chave na repetição
        toast.push({ tone: "danger", title: e instanceof ApiError && e.code === "PDF_CONVERTER_UNAVAILABLE" ? "PDF indisponível" : "Não foi possível gerar", description: errorMessage(e) });
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
  const errorCount = Object.keys(errors).length;

  const formPanel = (
    <form onSubmit={(e) => e.preventDefault()} noValidate className="space-y-6" aria-label="Formulário do documento">
      {errorCount > 0 && (
        <Alert tone="danger" title={`${errorCount} ${errorCount === 1 ? "campo precisa" : "campos precisam"} de atenção`}>
          Veja as mensagens ao lado de cada campo.
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

      <Field label="Nome do arquivo" help={`Resultado: ${filename}.docx`}>
        {(a) => <Input className="font-mono text-xs" value={pattern} onChange={(e) => setPattern(e.target.value)} {...a} data-testid="filename-pattern" />}
      </Field>

      <div className="sticky bottom-0 -mx-4 flex flex-wrap gap-2 border-t border-border bg-surface/95 px-4 py-3 backdrop-blur">
        <Button onClick={saveDraft}>
          <Save className="h-4 w-4" aria-hidden /> Salvar rascunho
        </Button>
        <Button variant="primary" loading={busy === "docx"} disabled={!!busy} onClick={() => generate("docx")} data-testid="generate-docx">
          <FileText className="h-4 w-4" aria-hidden /> Gerar DOCX
        </Button>
        <Button variant="primary" loading={busy === "pdf"} disabled={!!busy || !data.pdf_available} onClick={() => generate("pdf")} title={data.pdf_available ? undefined : "A conversão para PDF não está disponível neste ambiente"} data-testid="generate-pdf">
          <FileText className="h-4 w-4" aria-hidden /> Gerar PDF
        </Button>
        <Button variant="ghost" onClick={clearDraft} className="ml-auto">
          Limpar
        </Button>
      </div>
      {!data.pdf_available && <p className="text-xs text-warning">A conversão para PDF não está disponível neste ambiente (LibreOffice ausente). O DOCX funciona normalmente.</p>}
    </form>
  );

  return (
    <>
      {desktop ? (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,30rem)_minmax(0,1fr)]">
          <Card className="h-fit p-5">{formPanel}</Card>
          <div tabIndex={0} role="region" aria-label="Prévia do documento (área rolável)" className="doc-canvas max-h-[calc(100vh-9rem)] overflow-auto rounded-lg p-4">
            <p className="mb-2 text-center text-xs text-muted">Prévia atualizada enquanto você digita — campos em falta aparecem em amarelo.</p>
            <DocPreview doc={data.doc} fields={fields} values={values} />
          </div>
        </div>
      ) : (
        <Tabs value={mobileTab} onValueChange={setMobileTab} tabs={[{ value: "form", label: "Formulário" }, { value: "preview", label: "Prévia" }]} className="mb-4">
          <TabPanel value="form" className="pt-4"><Card className="p-4">{formPanel}</Card></TabPanel>
          <TabPanel value="preview" className="pt-4"><div tabIndex={0} role="region" aria-label="Prévia do documento (área rolável)" className="doc-canvas overflow-x-auto rounded-lg p-2"><DocPreview doc={data.doc} fields={fields} values={values} /></div></TabPanel>
        </Tabs>
      )}

      <Dialog open={!!jobId} onOpenChange={(o) => !o && setJobId(null)} title="Gerando seu documento" size="md">
        {jobId && <JobResult jobId={jobId} onClose={() => setJobId(null)} />}
      </Dialog>
    </>
  );
}

function UseLoader() {
  const { id } = useParams<{ id: string }>();
  const q = useQuery({ queryKey: ["form", id], queryFn: () => api.get<FormPayload>(`/generators/${id}/form`), retry: false, staleTime: 0 });
  const title = q.data?.generator.name ?? "Gerar documento";

  return (
    <AppShell wide>
      <PageHeader
        title={title}
        description="Preencha os campos — a prévia ao lado mostra o documento pronto."
        actions={q.data && <ModelNav id={id} current="use" />}
      />
      {q.isLoading ? (
        <div className="grid gap-6 lg:grid-cols-2"><Skeleton className="h-96" /><Skeleton className="h-96" /></div>
      ) : q.error ? (
        <Alert tone="danger" title="Não foi possível abrir o formulário">
          {errorMessage(q.error)}{" "}
          {q.error instanceof ApiError && q.error.code === "NOT_FOUND" && (
            <span>
              <Link href={`/generators/${id}/edit`} className="font-medium underline">Abra o editor</Link> e envie um documento .docx.
            </span>
          )}
        </Alert>
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
