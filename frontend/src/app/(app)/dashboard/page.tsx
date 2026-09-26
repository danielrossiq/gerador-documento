"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  ArchiveRestore,
  ArrowRight,
  CircleAlert,
  ClipboardCheck,
  Copy,
  FilePlus2,
  FileText,
  FileUp,
  Layers,
  Loader2,
  PencilRuler,
  Pin,
  Play,
  Search,
  Sparkles,
  Star,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { stepHrefs, nextHref } from "@/components/generators/steps";
import { AppShell, PageHeader } from "@/components/layout/app-shell";
import { HowItWorks, TrySampleButton } from "@/components/onboarding/samples";
import { ButtonLink } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Checkbox, Input, Select } from "@/components/ui/form";
import { ActionMenu, type MenuItem } from "@/components/ui/menu";
import { Badge, Card, EmptyState, ProgressBar, Skeleton } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import type { GeneratorOut, KitOut, Paged } from "@/lib/types";
import { cn, plural, timeAgo } from "@/lib/utils";

type Dash = {
  total_generators: number;
  documents_this_month: number;
  jobs_in_progress: number;
  jobs_with_problems: number;
  quota: { documents_per_month: number };
  recent: GeneratorOut[];
  kits: { total_kits: number; recent: KitOut[] };
};

const AVATAR_TONES = [
  "bg-primary-soft text-primary",
  "bg-success-soft text-success",
  "bg-warning-soft text-warning",
  "bg-danger-soft text-danger",
] as const;

function avatarClass(name: string): string {
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return AVATAR_TONES[h % AVATAR_TONES.length];
}

function ModelAvatar({ name }: { name: string }) {
  const letter = (name.trim()[0] ?? "?").toUpperCase();
  return (
    <span aria-hidden className={cn("grid h-10 w-10 shrink-0 place-items-center rounded-full text-base font-bold", avatarClass(name))}>
      {letter}
    </span>
  );
}

function PinButton({ pinned, name, onToggle }: { pinned: boolean; name: string; onToggle: () => void }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={pinned}
      aria-label={pinned ? `Desafixar ${name}` : `Fixar ${name} no topo`}
      title={pinned ? "Desafixar" : "Fixar no topo"}
      className={cn("grid h-8 w-8 shrink-0 place-items-center rounded-full transition-colors", pinned ? "text-warning" : "text-muted hover:bg-surface-2 hover:text-fg")}
    >
      <Star className="h-4 w-4" aria-hidden fill={pinned ? "currentColor" : "none"} />
    </button>
  );
}

/** Em que pé está o gerador e qual é a próxima ação — a mesma lógica das etapas Modelo → Campos → Revisão → Gerar. */
function statusOf(g: GeneratorOut) {
  const h = stepHrefs(g.id);
  if (!g.has_template) return { tone: "warning" as const, label: "Falta o documento", hint: "Envie o arquivo .docx para começar.", action: { label: "Enviar documento", href: h.template, icon: FileUp } };
  if (g.fields_count === 0) {
    const analysing = g.analysis_status === "pending" || g.analysis_status === "running";
    return { tone: "warning" as const, label: analysing ? "Analisando…" : "Sem campos", hint: "Marque no documento o que muda de um para outro.", action: { label: "Criar campos", href: h.fields, icon: PencilRuler } };
  }
  return { tone: "success" as const, label: "Pronto para gerar", hint: null, action: { label: "Gerar documento", href: h.generate, icon: Play } };
}

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

function GeneratorCard({ g, menu, onTogglePin }: { g: GeneratorOut; menu: MenuItem[]; onTogglePin: () => void }) {
  const st = statusOf(g);
  const Icon = st.action.icon;
  return (
    <li>
      <Card className={cn("flex h-full flex-col gap-3 p-4 transition-shadow hover:shadow-md", g.is_pinned && "ring-1 ring-warning/40")} data-testid="generator-card">
        <div className="flex items-start gap-3">
          <ModelAvatar name={g.name} />
          <div className="min-w-0 flex-1">
            <h3 className="font-semibold">
              <Link href={nextHref(g)} className="line-clamp-2 break-words hover:text-primary hover:underline">{g.name}</Link>
            </h3>
            <p className="line-clamp-1 text-xs text-muted">{g.status === "archived" ? "Arquivado · " : ""}{st.hint ?? g.description ?? "Sem descrição"}</p>
          </div>
          <PinButton pinned={g.is_pinned} name={g.name} onToggle={onTogglePin} />
        </div>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
          <Badge tone={st.tone} data-testid="generator-status">{st.label}</Badge>
          <span>
            {[g.has_template ? plural(g.fields_count, "campo", "campos") : null, g.documents_generated > 0 ? plural(g.documents_generated, "documento gerado", "documentos gerados") : null, `atualizado ${timeAgo(g.updated_at)}`]
              .filter(Boolean)
              .join(" · ")}
          </span>
        </div>
        <div className="mt-auto flex items-center gap-2 pt-1">
          <ButtonLink href={st.action.href} size="sm" variant={st.tone === "success" ? "primary" : "secondary"} className="flex-1 justify-center">
            <Icon className="h-3.5 w-3.5" aria-hidden /> {st.action.label}
          </ButtonLink>
          {st.tone === "success" && (
            <ButtonLink href={stepHrefs(g.id).batch} size="sm" title="Vários documentos de uma vez, a partir de uma planilha" aria-label={`Gerar vários documentos com ${g.name}`}>
              <Layers className="h-3.5 w-3.5" aria-hidden /> Vários
            </ButtonLink>
          )}
          <ActionMenu label={`Mais ações de ${g.name}`} items={menu} />
        </div>
      </Card>
    </li>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [sort, setSort] = useState("updated");
  const [toDelete, setToDelete] = useState<GeneratorOut | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 250);
    return () => clearTimeout(t);
  }, [q]);

  const dash = useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<Dash>("/dashboard") });
  const status = showArchived ? "archived" : "";
  const list = useQuery({
    queryKey: ["generators", debounced, status, sort],
    queryFn: () => api.get<Paged<GeneratorOut>>(`/generators?page_size=50&sort=${sort}${debounced ? `&q=${encodeURIComponent(debounced)}` : ""}${status ? `&status=${status}` : ""}`),
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["generators"] });
    qc.invalidateQueries({ queryKey: ["dashboard"] });
  };
  const act = useMutation({
    mutationFn: async (a: { kind: "duplicate" | "archive" | "unarchive" | "delete" | "pin" | "unpin"; g: GeneratorOut }) => {
      if (a.kind === "delete") return api.delete<undefined>(`/generators/${a.g.id}`);
      return api.post<GeneratorOut | undefined>(`/generators/${a.g.id}/${a.kind}`);
    },
    onSuccess: (res, v) => {
      refresh();
      setToDelete(null);
      if (v.kind === "duplicate") toast.push({ tone: "success", title: "Cópia criada", description: res && "name" in res ? `“${res.name}” já está na lista, pronta para ajustar.` : undefined });
      const msg = { archive: "Gerador arquivado.", unarchive: "Gerador restaurado.", delete: "Gerador excluído.", pin: "", unpin: "", duplicate: "" }[v.kind];
      if (msg) toast.push({ tone: "success", title: msg });
    },
    onError: (e) => toast.push({ tone: "danger", title: "Não foi possível concluir", description: errorMessage(e) }),
  });
  const togglePin = (g: GeneratorOut) => act.mutate({ kind: g.is_pinned ? "unpin" : "pin", g });

  function menuFor(g: GeneratorOut): MenuItem[] {
    const h = stepHrefs(g.id);
    const ready = g.has_template && g.fields_count > 0;
    return [
      { label: "Gerar um documento", icon: <Play className="h-4 w-4" aria-hidden />, onSelect: () => router.push(h.generate), disabled: !ready },
      { label: "Gerar vários (planilha)", icon: <Layers className="h-4 w-4" aria-hidden />, onSelect: () => router.push(h.batch), disabled: !ready },
      { separator: true },
      { label: g.has_template ? "Trocar o documento .docx" : "Enviar o documento .docx", icon: <FileUp className="h-4 w-4" aria-hidden />, onSelect: () => router.push(h.template) },
      { label: "Editar campos", icon: <PencilRuler className="h-4 w-4" aria-hidden />, onSelect: () => router.push(h.fields), disabled: !g.has_template },
      { label: "Revisar", icon: <ClipboardCheck className="h-4 w-4" aria-hidden />, onSelect: () => router.push(h.review), disabled: !ready },
      { separator: true },
      { label: g.is_pinned ? "Desafixar" : "Fixar no topo", icon: <Pin className="h-4 w-4" aria-hidden />, onSelect: () => togglePin(g) },
      { label: "Duplicar", icon: <Copy className="h-4 w-4" aria-hidden />, onSelect: () => act.mutate({ kind: "duplicate", g }) },
      g.status === "archived"
        ? { label: "Desarquivar", icon: <ArchiveRestore className="h-4 w-4" aria-hidden />, onSelect: () => act.mutate({ kind: "unarchive", g }) }
        : { label: "Arquivar", icon: <Archive className="h-4 w-4" aria-hidden />, onSelect: () => act.mutate({ kind: "archive", g }) },
      { separator: true },
      { label: "Excluir…", icon: <Trash2 className="h-4 w-4" aria-hidden />, danger: true, onSelect: () => setToDelete(g) },
    ];
  }

  const d = dash.data;
  const items = list.data?.items ?? [];
  const isNew = !!d && d.total_generators === 0 && d.kits.total_kits === 0 && !showArchived;
  const filtering = !!debounced || showArchived;

  return (
    <AppShell>
      <PageHeader
        title="Geradores"
        description={isNew ? "Comece criando o seu primeiro gerador." : "Cada gerador transforma um documento .docx em um formulário: preencha e baixe o documento pronto — um de cada vez ou vários com uma planilha."}
        actions={!isNew && <ButtonLink href="/generators/new" variant="primary"><FilePlus2 className="h-4 w-4" aria-hidden /> Novo gerador</ButtonLink>}
      />

      {dash.isLoading ? (
        <div className="space-y-4"><Skeleton className="h-14" /><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3"><Skeleton className="h-44" /><Skeleton className="h-44" /><Skeleton className="h-44" /></div></div>
      ) : dash.error ? (
        <Card className="p-6 text-sm text-danger" role="alert">Não foi possível carregar o painel: {errorMessage(dash.error)}</Card>
      ) : isNew ? (
        <HowItWorks />
      ) : d ? (
        <>
          <ActivityStrip d={d} />

          <section aria-labelledby="all-h" className="mb-10">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <h2 id="all-h" className="text-lg font-semibold">{showArchived ? "Geradores arquivados" : "Seus geradores"}</h2>
              <div className="flex flex-wrap items-center gap-2">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted" aria-hidden />
                  <Input aria-label="Buscar gerador" placeholder="Buscar" className="w-full pl-9 sm:w-52" value={q} onChange={(e) => setQ(e.target.value)} />
                </div>
                <Select aria-label="Ordenar" value={sort} onChange={(e) => setSort(e.target.value)} className="w-44">
                  <option value="updated">Mais recentes</option>
                  <option value="name">Nome (A–Z)</option>
                  <option value="created">Criados por último</option>
                </Select>
                <Checkbox label="Mostrar arquivados" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} className="text-muted" />
              </div>
            </div>

            {list.isLoading ? (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-44" />)}</div>
            ) : list.error ? (
              <Card className="p-6 text-sm text-danger" role="alert">{errorMessage(list.error)}</Card>
            ) : items.length === 0 ? (
              <EmptyState
                icon={<FileText className="h-9 w-9" aria-hidden />}
                title={filtering ? "Nenhum gerador encontrado" : "Nenhum gerador ainda"}
                description={filtering ? (showArchived ? "Não há geradores arquivados com esse filtro." : "Tente buscar por outra palavra.") : "Envie um documento .docx que você já usa para criar o primeiro."}
                action={!filtering ? <ButtonLink href="/generators/new" variant="primary"><FilePlus2 className="h-4 w-4" aria-hidden /> Novo gerador</ButtonLink> : undefined}
              />
            ) : (
              <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-label="Geradores">
                {items.map((g) => <GeneratorCard key={g.id} g={g} menu={menuFor(g)} onTogglePin={() => togglePin(g)} />)}
              </ul>
            )}
          </section>

          <section aria-labelledby="kits-h">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 id="kits-h" className="text-lg font-semibold">Kits de documentos</h2>
              {d.kits.total_kits > 0 && <Link href="/kits" className="inline-flex items-center gap-1 text-sm text-primary hover:underline">Ver todos os kits <ArrowRight className="h-3.5 w-3.5" aria-hidden /></Link>}
            </div>
            {d.kits.total_kits > 0 ? (
              <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {d.kits.recent.slice(0, 3).map((k) => (
                  <li key={k.id}>
                    <Card className="flex h-full flex-col gap-3 p-4">
                      <div className="flex items-start gap-3">
                        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-primary-soft text-primary" aria-hidden><Layers className="h-5 w-5" aria-hidden /></span>
                        <div className="min-w-0 flex-1">
                          <h3 className="font-semibold"><Link href={k.has_documents ? `/kits/${k.id}/use` : `/kits/${k.id}/edit`} className="line-clamp-2 hover:text-primary hover:underline">{k.name}</Link></h3>
                          <p className="mt-0.5 text-xs text-muted">{plural(k.items_count, "documento", "documentos")} · {plural(k.fields_count, "dado em comum", "dados em comum")}</p>
                        </div>
                      </div>
                      <div className="mt-auto pt-1">
                        {k.has_documents ? (
                          <ButtonLink href={`/kits/${k.id}/use`} size="sm" variant="primary" className="w-full justify-center"><Play className="h-3.5 w-3.5" aria-hidden /> Preencher kit</ButtonLink>
                        ) : (
                          <ButtonLink href={`/kits/${k.id}/edit`} size="sm" className="w-full justify-center">Continuar configurando</ButtonLink>
                        )}
                      </div>
                    </Card>
                  </li>
                ))}
              </ul>
            ) : (
              <Card className="flex flex-wrap items-center gap-4 border-dashed p-5">
                <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-primary-soft text-primary" aria-hidden><Layers className="h-5 w-5" aria-hidden /></span>
                <div className="min-w-0 flex-1 basis-60">
                  <p className="font-semibold">Documentos que sempre andam juntos?</p>
                  <p className="text-sm text-muted">Um kit junta vários geradores (contrato + recibo + termo…) e você preenche nome, CPF e endereço <strong className="text-fg">uma vez só</strong> para gerar todos.</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <TrySampleButton kind="kit" size="sm" />
                  {d.total_generators >= 2 && <ButtonLink href="/kits/new" size="sm" variant="primary">Criar um kit</ButtonLink>}
                </div>
              </Card>
            )}
          </section>
        </>
      ) : null}

      <ConfirmDialog
        open={!!toDelete}
        onOpenChange={(o) => !o && setToDelete(null)}
        title="Excluir gerador?"
        description={toDelete ? `“${toDelete.name}” deixará de aparecer nas suas listas. O histórico de documentos já gerados é mantido.` : undefined}
        confirmLabel="Excluir gerador"
        danger
        loading={act.isPending}
        onConfirm={() => toDelete && act.mutate({ kind: "delete", g: toDelete })}
      />
    </AppShell>
  );
}
