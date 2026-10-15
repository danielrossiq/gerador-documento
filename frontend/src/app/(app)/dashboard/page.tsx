"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CircleAlert, ClipboardPaste, FilePlus2, Layers, Loader2, Play, Sparkles } from "lucide-react";
import Link from "next/link";
import { nextHref, stepHrefs } from "@/components/generators/steps";
import { AnalysisStep, DocxDropzone, UploadErrorAlert, useNewModelUpload } from "@/components/generators/template-upload";
import { PasteBatch } from "@/components/home/paste-batch";
import { AppShell, useMe } from "@/components/layout/app-shell";
import { isReady, ModelAvatar, statusOf } from "@/components/models/model-card";
import { HowItWorks, TrySampleButton } from "@/components/onboarding/samples";
import { ButtonLink } from "@/components/ui/button";
import { Card, ProgressBar, Skeleton } from "@/components/ui/misc";
import { api, errorMessage } from "@/lib/api";
import type { GeneratorOut, KitOut, Paged } from "@/lib/types";
import { plural } from "@/lib/utils";

type Dash = {
  total_generators: number;
  documents_this_month: number;
  jobs_in_progress: number;
  jobs_with_problems: number;
  quota: { documents_per_month: number };
  recent: GeneratorOut[];
  kits: { total_kits: number; recent: KitOut[] };
};

const QUICK = 6;

/** Uma linha de atividade — só aparece quando há algo a dizer. */
function ActivityStrip({ d }: { d: Dash }) {
  const quota = d.quota.documents_per_month;
  const used = d.documents_this_month;
  if (!used && !d.jobs_in_progress && !d.jobs_with_problems) return null;
  return (
    <div className="mb-6 flex flex-wrap items-center gap-x-6 gap-y-3 rounded-lg border border-border bg-surface px-4 py-3 text-sm" aria-label="Atividade do mês">
      <div className="flex min-w-56 flex-1 items-center gap-3">
        <Sparkles className="h-4 w-4 shrink-0 text-success" aria-hidden />
        <span><strong className="tabular-nums">{used}</strong> {used === 1 ? "documento gerado" : "documentos gerados"} este mês{quota > 0 ? ` (limite: ${quota})` : ""}</span>
        {quota > 0 && <div className="hidden w-32 sm:block"><ProgressBar value={used / quota} label="Limite mensal usado" tone={used / quota > 0.9 ? "danger" : "success"} /></div>}
      </div>
      {d.jobs_in_progress > 0 && (
        <Link href="/history" className="flex items-center gap-1.5 text-muted hover:text-fg">
          <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden /> {plural(d.jobs_in_progress, "geração em andamento", "gerações em andamento")}
        </Link>
      )}
      {d.jobs_with_problems > 0 && (
        <Link href="/history" className="flex items-center gap-1.5 font-medium text-danger hover:underline">
          <CircleAlert className="h-4 w-4" aria-hidden /> {plural(d.jobs_with_problems, "geração precisa", "gerações precisam")} de atenção
        </Link>
      )}
    </div>
  );
}

/** Atalho de um modelo: pronto → Preencher / Em lote; senão, a próxima etapa que falta. */
function QuickModel({ g }: { g: GeneratorOut }) {
  const st = statusOf(g);
  const h = stepHrefs(g.id);
  const ready = isReady(g);
  return (
    <li className="flex items-center gap-3 rounded-lg border border-border bg-surface p-3" data-testid="quick-model">
      <ModelAvatar name={g.name} className="h-9 w-9 text-sm" />
      <div className="min-w-0 flex-1">
        <Link href={nextHref(g)} className="block truncate font-medium hover:text-primary hover:underline">{g.name}</Link>
        <p className="truncate text-xs text-muted">
          {ready ? [plural(g.fields_count, "campo", "campos"), g.documents_generated ? plural(g.documents_generated, "gerado", "gerados") : null].filter(Boolean).join(" · ") : st.label}
        </p>
      </div>
      {ready ? (
        <div className="flex shrink-0 gap-1.5">
          <ButtonLink href={h.generate} size="sm" variant="primary" aria-label={`Preencher ${g.name}`}><Play className="h-3.5 w-3.5" aria-hidden /> <span className="hidden sm:inline">Preencher</span></ButtonLink>
          <ButtonLink href={h.batch} size="sm" aria-label={`Gerar em lote com ${g.name}`} title="Vários documentos de uma vez, a partir de uma planilha"><Layers className="h-3.5 w-3.5" aria-hidden /> <span className="hidden sm:inline">Em lote</span></ButtonLink>
        </div>
      ) : (
        <ButtonLink href={st.action.href} size="sm" className="shrink-0">{st.action.label}</ButtonLink>
      )}
    </li>
  );
}

/** Página inicial: começar um modelo, gerar em lote colando uma planilha e atalhos para o que já existe. */
export default function HomePage() {
  const me = useMe().data;
  const upload = useNewModelUpload();
  const dash = useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<Dash>("/dashboard") });
  const list = useQuery({ queryKey: ["generators", "home"], queryFn: () => api.get<Paged<GeneratorOut>>("/generators?page_size=50&sort=updated") });

  const d = dash.data;
  const all = list.data?.items ?? [];
  const ready = all.filter(isReady);
  const quick = [...all].sort((a, b) => Number(b.is_pinned) - Number(a.is_pinned)).slice(0, QUICK);
  const isNew = !!d && d.total_generators === 0 && d.kits.total_kits === 0;
  const firstName = me?.user.name.split(" ")[0];

  return (
    <AppShell>
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight">{firstName ? `Olá, ${firstName}` : "Início"}</h1>
        <p className="mt-1 text-sm text-muted">{isNew ? "Vamos transformar o seu primeiro documento em um modelo que se preenche sozinho." : "Crie um modelo novo, gere em lote colando uma planilha ou continue de onde parou."}</p>
      </div>

      {d && <ActivityStrip d={d} />}

      <div className="mb-8 grid gap-4 lg:grid-cols-5">
        <Card className="flex flex-col p-5 lg:col-span-2" data-testid="home-new-model">
          <h2 className="flex items-center gap-2 text-lg font-semibold"><FilePlus2 className="h-5 w-5 text-primary" aria-hidden /> Novo modelo</h2>
          <p className="mb-4 mt-1 text-sm text-muted">Envie um documento que você já usa. Nome, CPF, datas e valores viram campos sugeridos na hora.</p>
          {upload.error && <UploadErrorAlert error={upload.error} />}
          {upload.generatorId ? (
            <AnalysisStep generatorId={upload.generatorId} />
          ) : (
            <DocxDropzone compact busy={upload.uploading} file={upload.file} onPick={(f) => upload.send(f)} />
          )}
          <div className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-4 text-sm">
            <span className="text-muted">Sem documento à mão?</span>
            <TrySampleButton size="sm" />
          </div>
        </Card>

        <Card className="p-5 lg:col-span-3" data-testid="home-paste">
          <h2 className="flex items-center gap-2 text-lg font-semibold"><ClipboardPaste className="h-5 w-5 text-primary" aria-hidden /> Gerar em lote colando uma planilha</h2>
          <p className="mb-4 mt-1 text-sm text-muted">Cole as linhas com os títulos das colunas: a gente descobre qual modelo usar e prepara um documento por linha.</p>
          {list.isLoading ? (
            <Skeleton className="h-40" />
          ) : ready.length ? (
            <PasteBatch models={ready} />
          ) : (
            <div className="grid min-h-40 place-items-center rounded-md border border-dashed border-border-strong p-6 text-center text-sm text-muted">
              <p>Assim que você tiver um modelo pronto (com campos), cole aqui uma planilha para gerar vários documentos de uma vez.</p>
            </div>
          )}
        </Card>
      </div>

      {dash.error ? (
        <Card className="p-6 text-sm text-danger" role="alert">Não foi possível carregar o painel: {errorMessage(dash.error)}</Card>
      ) : isNew ? (
        <HowItWorks actions={false} />
      ) : (
        <div className="grid gap-8 lg:grid-cols-3">
          <section aria-labelledby="quick-h" className="min-w-0 lg:col-span-2">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 id="quick-h" className="text-lg font-semibold">Seus modelos</h2>
              <Link href="/models" className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
                Ver todos{d ? ` (${d.total_generators})` : ""} <ArrowRight className="h-3.5 w-3.5" aria-hidden />
              </Link>
            </div>
            {list.isLoading ? (
              <div className="grid gap-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-16" />)}</div>
            ) : (
              <ul className="grid gap-2" aria-label="Atalhos para os modelos">
                {quick.map((g) => <QuickModel key={g.id} g={g} />)}
              </ul>
            )}
          </section>

          <section aria-labelledby="kits-h" className="min-w-0">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 id="kits-h" className="text-lg font-semibold">Kits</h2>
              {!!d?.kits.total_kits && <Link href="/kits" className="inline-flex items-center gap-1 text-sm text-primary hover:underline">Ver todos <ArrowRight className="h-3.5 w-3.5" aria-hidden /></Link>}
            </div>
            {d && d.kits.total_kits > 0 ? (
              <ul className="space-y-2">
                {d.kits.recent.slice(0, 4).map((k) => (
                  <li key={k.id} className="flex items-center gap-3 rounded-lg border border-border bg-surface p-3">
                    <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-primary-soft text-primary" aria-hidden><Layers className="h-4 w-4" /></span>
                    <div className="min-w-0 flex-1">
                      <Link href={k.has_documents ? `/kits/${k.id}/use` : `/kits/${k.id}/edit`} className="block truncate font-medium hover:text-primary hover:underline">{k.name}</Link>
                      <p className="truncate text-xs text-muted">{plural(k.items_count, "documento", "documentos")} · {plural(k.fields_count, "dado em comum", "dados em comum")}</p>
                    </div>
                    {k.has_documents ? (
                      <ButtonLink href={`/kits/${k.id}/use`} size="sm" variant="primary" aria-label={`Preencher o kit ${k.name}`}><Play className="h-3.5 w-3.5" aria-hidden /></ButtonLink>
                    ) : (
                      <ButtonLink href={`/kits/${k.id}/edit`} size="sm">Configurar</ButtonLink>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <Card className="border-dashed p-4 text-sm">
                <p className="font-medium">Documentos que sempre andam juntos?</p>
                <p className="mt-1 text-muted">Um kit junta vários modelos (contrato + recibo + termo…): você preenche nome, CPF e endereço <strong className="text-fg">uma vez só</strong>.</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <TrySampleButton kind="kit" size="sm" />
                  {(d?.total_generators ?? 0) >= 2 && <ButtonLink href="/kits/new" size="sm" variant="primary">Criar um kit</ButtonLink>}
                </div>
              </Card>
            )}
          </section>
        </div>
      )}
    </AppShell>
  );
}
