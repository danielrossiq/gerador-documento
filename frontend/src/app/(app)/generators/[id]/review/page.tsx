"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, CheckCircle2, FileText, Info, Layers, Sparkles, Wrench, XCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { DocPreview } from "@/components/form/doc-preview";
import { GeneratorHeader, stepHrefs } from "@/components/generators/steps";
import { AppShell } from "@/components/layout/app-shell";
import { ButtonLink } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { Alert, Card, Skeleton } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { FILENAME_TOKENS, previewFilename, unknownTokens } from "@/lib/fields/filename";
import { fieldIssues, occurrenceCounts, type FieldIssue } from "@/lib/fields/issues";
import { exampleValues } from "@/lib/fields/samples";
import type { FieldOut, FormPayload, GeneratorOut } from "@/lib/types";
import { cn, plural } from "@/lib/utils";

function Check({ ok, warn, children }: { ok: boolean; warn?: boolean; children: React.ReactNode }) {
  const Icon = ok ? CheckCircle2 : warn ? AlertTriangle : XCircle;
  return (
    <li className="flex items-start gap-2 text-sm">
      <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", ok ? "text-success" : warn ? "text-warning" : "text-danger")} aria-hidden />
      <span className="sr-only">{ok ? "Concluído:" : warn ? "Atenção:" : "Pendente:"}</span>
      <div className="min-w-0 flex-1">{children}</div>
    </li>
  );
}

/** Onde e como os documentos gerados são nomeados: padrão com {códigos} + prévia do resultado. */
function FilenameSettings({ generator, fields, sample, onSaved }: { generator: GeneratorOut; fields: FieldOut[]; sample: Record<string, unknown>; onSaved: (g: GeneratorOut) => void }) {
  const toast = useToast();
  const [pattern, setPattern] = useState(generator.filename_pattern);
  const [desc, setDesc] = useState(generator.description ?? "");
  const [saving, setSaving] = useState(false);
  const unknown = unknownTokens(pattern, fields);

  async function save(patch: Record<string, unknown>, what: string) {
    setSaving(true);
    try {
      onSaved(await api.patch<GeneratorOut>(`/generators/${generator.id}`, patch));
      toast.push({ tone: "success", title: `${what} salvo` });
    } catch (e) {
      toast.push({ tone: "danger", title: `Não foi possível salvar: ${what.toLowerCase()}`, description: errorMessage(e) });
    } finally {
      setSaving(false);
    }
  }
  const insert = (token: string) => setPattern((p) => `${p}${p && !p.endsWith("_") ? "_" : ""}{${token}}`);

  return (
    <Card className="space-y-4 p-5">
      <h2 className="text-base font-semibold">Detalhes do modelo</h2>
      <Field label="Descrição" help="Aparece no painel, para lembrar para que serve este modelo.">
        {(a) => <Input {...a} value={desc} maxLength={500} onChange={(e) => setDesc(e.target.value)} onBlur={() => desc !== (generator.description ?? "") && save({ description: desc }, "Descrição")} placeholder="Ex.: Contrato padrão de prestação de serviços" />}
      </Field>
      <div className="space-y-2">
        <Field
          label="Nome dos arquivos gerados"
          help={unknown.length ? undefined : `Exemplo: ${previewFilename(pattern, fields, sample, generator.name)}.docx`}
          error={unknown.length ? `Não existe campo com o código ${unknown.map((u) => `{${u}}`).join(", ")}. Ele vai sair em branco.` : null}
        >
          {(a) => (
            <Input
              {...a}
              className="font-mono text-xs"
              value={pattern}
              onChange={(e) => setPattern(e.target.value)}
              onBlur={() => pattern.trim() && pattern !== generator.filename_pattern && save({ filename_pattern: pattern }, "Nome dos arquivos")}
              data-testid="review-filename"
            />
          )}
        </Field>
        <div>
          <p className="mb-1 text-xs text-muted">Clique para acrescentar ao nome:</p>
          <div className="flex flex-wrap gap-1.5">
            {fields.slice(0, 12).map((f) => (
              <button key={f.id} type="button" className="rounded-full border border-border bg-surface-2 px-2 py-0.5 text-xs hover:border-primary hover:text-primary" onClick={() => insert(f.name)}>
                + {f.label}
              </button>
            ))}
            {FILENAME_TOKENS.map((t) => (
              <button key={t.token} type="button" className="rounded-full border border-dashed border-border-strong px-2 py-0.5 text-xs text-muted hover:border-primary hover:text-primary" onClick={() => insert(t.token)}>
                + {t.label}
              </button>
            ))}
          </div>
          {pattern !== generator.filename_pattern && (
            <p className="mt-2 text-xs text-muted" aria-live="polite">{saving ? "Salvando…" : "Alteração ainda não salva — clique fora do campo para salvar."}</p>
          )}
        </div>
      </div>
    </Card>
  );
}

function ReviewView({ data, suggestions }: { data: FormPayload; suggestions: number }) {
  const qc = useQueryClient();
  const id = data.generator.id;
  const [generator, setGenerator] = useState(data.generator);
  const [mode, setMode] = useState<"example" | "labels">("example");
  const fields = data.fields;
  const counts = useMemo(() => occurrenceCounts(data.doc), [data.doc]);
  const issues = useMemo(() => fieldIssues(fields, counts), [fields, counts]);
  const sample = useMemo(() => exampleValues(fields, data.doc), [fields, data.doc]);
  const errors = issues.filter((i) => i.severity === "error");
  const warnings = issues.filter((i) => i.severity === "warning");
  const byField = useMemo(() => Object.fromEntries(fields.map((f) => [f.id, f])), [fields]);
  const required = fields.filter((f) => f.required).length;
  const inBatch = fields.filter((f) => f.include_in_batch).length;
  const h = stepHrefs(id);

  const issueItem = (i: FieldIssue) => (
    <Check key={`${i.fieldId}-${i.kind}`} ok={false} warn={i.severity === "warning"}>
      <p><strong>{byField[i.fieldId]?.label ?? "Campo"}</strong>: {i.message}</p>
      <Link href={`${h.fields}?field=${i.fieldId}`} className="mt-0.5 inline-flex items-center gap-1 text-xs font-medium text-primary underline underline-offset-2">
        <Wrench className="h-3 w-3" aria-hidden /> Corrigir no editor
      </Link>
    </Check>
  );

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
      <div className="space-y-4">
        <Card className="p-5" data-testid="review-checklist">
          <h2 className="mb-3 text-base font-semibold">O que conferir</h2>
          <ul className="space-y-3">
            <Check ok>Documento enviado <span className="text-muted">(versão {data.version.version_number})</span></Check>
            <Check ok={fields.length > 0}>
              {fields.length > 0 ? (
                <>
                  {plural(fields.length, "campo", "campos")} <span className="text-muted">· {required} {required === 1 ? "obrigatório" : "obrigatórios"} · {inBatch} na planilha</span>
                </>
              ) : (
                <>Nenhum campo ainda. <Link href={h.fields} className="text-primary underline">Criar campos</Link></>
              )}
            </Check>
            {errors.map(issueItem)}
            {warnings.map(issueItem)}
            {suggestions > 0 && (
              <li className="flex items-start gap-2 text-sm">
                <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
                <div>
                  {plural(suggestions, "sugestão de campo ainda não revisada", "sugestões de campo ainda não revisadas")}.{" "}
                  <Link href={`${h.fields}?panel=suggestions`} className="text-primary underline underline-offset-2">Revisar</Link>
                  <p className="text-xs text-muted">Opcional: são trechos que parecem mudar e ainda não viraram campo.</p>
                </div>
              </li>
            )}
          </ul>
          <div className="mt-4">
            {errors.length > 0 ? (
              <Alert tone="danger" title={`${plural(errors.length, "item precisa", "itens precisam")} de correção`}>Dá para gerar mesmo assim, mas o resultado pode sair incompleto.</Alert>
            ) : warnings.length > 0 ? (
              <Alert tone="warning" title="Quase pronto">Os avisos acima não impedem a geração, mas podem confundir quem preenche.</Alert>
            ) : fields.length > 0 ? (
              <Alert tone="success" title="Tudo pronto para gerar">Confira a prévia ao lado e siga para a geração.</Alert>
            ) : null}
          </div>
        </Card>

        <FilenameSettings generator={generator} fields={fields} sample={sample} onSaved={(g) => { setGenerator(g); qc.invalidateQueries({ queryKey: ["form", id] }); }} />

        <Card className="space-y-3 p-5">
          <h2 className="text-base font-semibold">Próximo passo: gerar</h2>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
            <ButtonLink href={h.generate} variant="primary" className="justify-center" data-testid="review-go-use">
              <FileText className="h-4 w-4" aria-hidden /> Gerar um documento
            </ButtonLink>
            <ButtonLink href={h.batch} className="justify-center" data-testid="review-go-batch">
              <Layers className="h-4 w-4" aria-hidden /> Gerar vários (planilha)
            </ButtonLink>
          </div>
          {!data.pdf_available && (
            <p className="flex items-start gap-1.5 text-xs text-warning">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /> Neste ambiente só é possível gerar em Word (.docx): o conversor de PDF não está instalado no servidor.
            </p>
          )}
        </Card>
      </div>

      <section aria-labelledby="pv-h" className="min-w-0">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h2 id="pv-h" className="text-base font-semibold">Prévia do documento</h2>
          <fieldset className="inline-flex rounded-lg border border-border bg-surface-2 p-0.5 text-sm">
            <legend className="sr-only">Mostrar a prévia</legend>
            {(
              [["example", "Com dados de exemplo"], ["labels", "Com os nomes dos campos"]] as const
            ).map(([v, t]) => (
              <label key={v} className={cn("cursor-pointer rounded-md px-3 py-1.5 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-primary", mode === v ? "bg-surface font-medium shadow-sm" : "text-muted")}>
                <input type="radio" name="pv-mode" value={v} checked={mode === v} onChange={() => setMode(v)} className="sr-only" data-testid={`pv-${v}`} />
                {t}
              </label>
            ))}
          </fieldset>
        </div>
        <p className="mb-2 text-xs text-muted">
          {mode === "example"
            ? "Valores de exemplo (em verde) vêm do exemplo configurado em cada campo ou do texto original. Nada disso é salvo."
            : "Cada trecho em amarelo é um campo que será preenchido."}{" "}
          A prévia é uma aproximação; o arquivo gerado mantém a formatação do Word.
        </p>
        <div tabIndex={0} role="region" aria-label="Prévia do documento (área rolável)" className="doc-canvas max-h-[calc(100vh-14rem)] overflow-auto rounded-lg p-2 sm:p-4">
          <DocPreview doc={data.doc} fields={fields} values={mode === "example" ? sample : {}} />
        </div>
      </section>
    </div>
  );
}

export default function ReviewPage() {
  const { id } = useParams<{ id: string }>();
  const q = useQuery({ queryKey: ["form", id], queryFn: () => api.get<FormPayload>(`/generators/${id}/form`), retry: false, staleTime: 0 });
  const sug = useQuery({ queryKey: ["suggestions", id], queryFn: () => api.get<{ items: unknown[] }>(`/generators/${id}/suggestions`), enabled: !!q.data });
  const g = q.data?.generator;

  return (
    <AppShell wide>
      {g ? (
        <GeneratorHeader id={id} name={g.name} step="review" hasTemplate={g.has_template} fieldsCount={q.data!.fields.length} description="Confira como o documento vai ficar e se falta ajustar algum campo.">
          {q.data!.fields.length > 0 && (
            <ButtonLink href={stepHrefs(id).generate} variant="primary" size="sm">
              Próximo: Gerar <ArrowRight className="h-4 w-4" aria-hidden />
            </ButtonLink>
          )}
        </GeneratorHeader>
      ) : (
        <Skeleton className="mb-6 h-24 w-full" />
      )}
      {q.isLoading ? (
        <div className="grid gap-6 lg:grid-cols-[26rem_1fr]"><Skeleton className="h-96" /><Skeleton className="h-96" /></div>
      ) : q.error ? (
        <Alert tone="danger" title="Não foi possível abrir a revisão">
          {errorMessage(q.error)} <ButtonLink href={stepHrefs(id).template} size="sm" className="ml-2">Ir para a etapa Documento</ButtonLink>
        </Alert>
      ) : (
        <ReviewView data={q.data!} suggestions={sug.data?.items.length ?? 0} />
      )}
    </AppShell>
  );
}
