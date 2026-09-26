"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  ArchiveRestore,
  ArrowRight,
  CircleAlert,
  Copy,
  FilePlus2,
  FileText,
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
import { AppShell, PageHeader, useMe } from "@/components/layout/app-shell";
import { HowItWorks, TrySampleButton } from "@/components/onboarding/samples";
import { Button } from "@/components/ui/button";
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

function ModelAvatar({ name, size = "md" }: { name: string; size?: "md" | "sm" }) {
  const letter = (name.trim()[0] ?? "?").toUpperCase();
  return (
    <span aria-hidden className={cn("grid shrink-0 place-items-center rounded-full font-bold", avatarClass(name), size === "md" ? "h-10 w-10 text-base" : "h-8 w-8 text-sm")}>
      {letter}
    </span>
  );
}

function PinButton({ pinned, onToggle }: { pinned: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onToggle();
      }}
      aria-pressed={pinned}
      aria-label={pinned ? "Desfixar modelo" : "Fixar modelo"}
      title={pinned ? "Desfixar" : "Fixar no topo"}
      className={cn("grid h-8 w-8 shrink-0 place-items-center rounded-full transition-colors", pinned ? "text-warning" : "text-muted hover:bg-surface-2 hover:text-fg")}
    >
      <Star className="h-4 w-4" aria-hidden fill={pinned ? "currentColor" : "none"} />
    </button>
  );
}

/** Uma linha de atividade no lugar de 4 cartões com números — só aparece quando há algo a dizer. */
function ActivityStrip({ d }: { d: Dash }) {
  const quota = d.quota.documents_per_month;
  const used = d.documents_this_month;
  if (!used && !d.jobs_in_progress && !d.jobs_with_problems) return null;
  return (
    <div className="mb-6 flex flex-wrap items-center gap-x-6 gap-y-3 rounded-lg border border-border bg-surface px-4 py-3 text-sm" aria-label="Atividade do mês">
      <div className="flex min-w-56 flex-1 items-center gap-3">
        <Sparkles className="h-4 w-4 shrink-0 text-success" aria-hidden />
        <span><strong className="tabular-nums">{used}</strong> {used === 1 ? "documento gerado" : "documentos gerados"} este mês</span>
        {quota > 0 && <div className="hidden w-32 sm:block"><ProgressBar value={used / quota} label="Cota mensal usada" tone={used / quota > 0.9 ? "danger" : "success"} /></div>}
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

export default function DashboardPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useToast();
  const me = useMe().data;
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
      if (a.kind === "delete") return api.delete(`/generators/${a.g.id}`);
      return api.post(`/generators/${a.g.id}/${a.kind}`);
    },
    onSuccess: (_d, v) => {
      refresh();
      setToDelete(null);
      const msg = { duplicate: "Modelo duplicado.", archive: "Modelo arquivado.", unarchive: "Modelo restaurado.", delete: "Modelo excluído.", pin: "", unpin: "" }[v.kind];
      if (msg) toast.push({ tone: "success", title: msg });
    },
    onError: (e) => toast.push({ tone: "danger", title: "Não foi possível concluir", description: errorMessage(e) }),
  });
  const togglePin = (g: GeneratorOut) => act.mutate({ kind: g.is_pinned ? "unpin" : "pin", g });
  const openHref = (g: GeneratorOut) => (g.has_template ? `/generators/${g.id}/use` : `/generators/${g.id}/edit`);

  function menuFor(g: GeneratorOut): MenuItem[] {
    return [
      { label: "Preencher", icon: <Play className="h-4 w-4" aria-hidden />, onSelect: () => router.push(`/generators/${g.id}/use`), disabled: !g.has_template },
      { label: "Gerar em lote", icon: <Layers className="h-4 w-4" aria-hidden />, onSelect: () => router.push(`/generators/${g.id}/batch`), disabled: !g.has_template },
      { label: "Editar campos", icon: <PencilRuler className="h-4 w-4" aria-hidden />, onSelect: () => router.push(`/generators/${g.id}/edit`) },
      { separator: true },
      { label: g.is_pinned ? "Desfixar" : "Fixar no topo", icon: <Pin className="h-4 w-4" aria-hidden />, onSelect: () => togglePin(g) },
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
  const firstName = me?.user.name.split(" ")[0];
  const isNew = !!d && d.total_generators === 0 && d.kits.total_kits === 0;

  return (
    <AppShell>
      <PageHeader
        title={firstName ? `Olá, ${firstName}` : "Painel"}
        description={isNew ? undefined : "O que você quer gerar hoje?"}
        actions={
          !isNew && (
            <>
              <Link href="/kits/new"><Button><Layers className="h-4 w-4" aria-hidden /> Novo kit</Button></Link>
              <Link href="/generators/new"><Button variant="primary"><FilePlus2 className="h-4 w-4" aria-hidden /> Novo modelo</Button></Link>
            </>
          )
        }
      />

      {dash.isLoading ? (
        <div className="space-y-4"><Skeleton className="h-14" /><div className="grid gap-3 sm:grid-cols-3"><Skeleton className="h-36" /><Skeleton className="h-36" /><Skeleton className="h-36" /></div></div>
      ) : isNew ? (
        <HowItWorks />
      ) : d ? (
        <>
          <ActivityStrip d={d} />

          {d.recent.length > 0 && (
            <section aria-labelledby="recent-h" className="mb-10">
              <h2 id="recent-h" className="mb-3 text-lg font-semibold">Preencher agora</h2>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {d.recent.map((g) => (
                  <Card key={g.id} className={cn("group flex flex-col gap-3 p-4 transition-shadow hover:shadow-md", g.is_pinned && "ring-1 ring-warning/40")}>
                    <div className="flex items-start gap-3">
                      <ModelAvatar name={g.name} />
                      <div className="min-w-0 flex-1">
                        <Link href={openHref(g)} className="line-clamp-2 font-semibold hover:text-primary hover:underline">{g.name}</Link>
                        <p className="mt-0.5 text-xs text-muted">
                          {g.has_template ? `${plural(g.fields_count, "campo", "campos")} · ${plural(g.documents_generated, "documento gerado", "documentos gerados")}` : "Falta enviar o documento .docx"}
                        </p>
                      </div>
                      <PinButton pinned={g.is_pinned} onToggle={() => togglePin(g)} />
                    </div>
                    <div className="mt-auto flex items-center gap-2 pt-1">
                      {g.has_template ? (
                        <>
                          <Link href={`/generators/${g.id}/use`} className="flex-1">
                            <Button size="sm" variant="primary" className="w-full justify-center"><Play className="h-3.5 w-3.5" aria-hidden /> Preencher</Button>
                          </Link>
                          <Link href={`/generators/${g.id}/batch`} title="Vários documentos de uma vez, a partir de uma planilha">
                            <Button size="sm"><Layers className="h-3.5 w-3.5" aria-hidden /> Lote</Button>
                          </Link>
                        </>
                      ) : (
                        <Link href={`/generators/${g.id}/edit`} className="flex-1">
                          <Button size="sm" className="w-full justify-center"><PencilRuler className="h-3.5 w-3.5" aria-hidden /> Continuar configurando</Button>
                        </Link>
                      )}
                    </div>
                  </Card>
                ))}
              </div>
            </section>
          )}

          <section aria-labelledby="kits-h" className="mb-10">
            <div className="mb-3 flex items-center justify-between">
              <h2 id="kits-h" className="text-lg font-semibold">Kits</h2>
              {d.kits.total_kits > 0 && <Link href="/kits" className="inline-flex items-center gap-1 text-sm text-primary hover:underline">Ver todos <ArrowRight className="h-3.5 w-3.5" aria-hidden /></Link>}
            </div>
            {d.kits.total_kits > 0 ? (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {d.kits.recent.slice(0, 3).map((k) => (
                  <Card key={k.id} className="flex flex-col gap-3 p-4">
                    <div className="flex items-start gap-3">
                      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-primary-soft text-primary" aria-hidden><Layers className="h-5 w-5" aria-hidden /></span>
                      <div className="min-w-0 flex-1">
                        <Link href={k.has_documents ? `/kits/${k.id}/use` : `/kits/${k.id}/edit`} className="line-clamp-2 font-semibold hover:text-primary hover:underline">{k.name}</Link>
                        <p className="mt-0.5 text-xs text-muted">{plural(k.items_count, "documento", "documentos")} · {plural(k.fields_count, "dado em comum", "dados em comum")}</p>
                      </div>
                    </div>
                    <div className="mt-auto flex items-center gap-2 pt-1">
                      {k.has_documents ? (
                        <Link href={`/kits/${k.id}/use`} className="flex-1"><Button size="sm" variant="primary" className="w-full justify-center"><Play className="h-3.5 w-3.5" aria-hidden /> Preencher kit</Button></Link>
                      ) : (
                        <Link href={`/kits/${k.id}/edit`} className="flex-1"><Button size="sm" className="w-full justify-center">Continuar configurando</Button></Link>
                      )}
                    </div>
                  </Card>
                ))}
              </div>
            ) : (
              <Card className="flex flex-wrap items-center gap-4 border-dashed p-5">
                <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-primary-soft text-primary" aria-hidden><Layers className="h-5 w-5" aria-hidden /></span>
                <div className="min-w-60 flex-1">
                  <p className="font-semibold">Documentos que sempre andam juntos?</p>
                  <p className="text-sm text-muted">Um kit junta vários modelos (contrato + recibo + termo…) e você preenche nome, CPF e endereço <strong className="text-fg">uma vez só</strong> para gerar todos.</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <TrySampleButton kind="kit" size="sm" />
                  {d.total_generators >= 2 && <Link href="/kits/new"><Button size="sm" variant="primary">Criar um kit</Button></Link>}
                </div>
              </Card>
            )}
          </section>

          <section aria-labelledby="all-h">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <h2 id="all-h" className="text-lg font-semibold">Todos os modelos</h2>
              {(d.total_generators > 0 || showArchived) && (
                <div className="flex flex-wrap items-center gap-2">
                  <div className="relative">
                    <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted" aria-hidden />
                    <Input aria-label="Buscar modelo" placeholder="Buscar" className="w-52 pl-9" value={q} onChange={(e) => setQ(e.target.value)} />
                  </div>
                  <Select aria-label="Ordenar" value={sort} onChange={(e) => setSort(e.target.value)} className="w-48">
                    <option value="updated">Atualização recente</option>
                    <option value="name">Nome (A–Z)</option>
                    <option value="created">Criação recente</option>
                  </Select>
                  <Checkbox label="Arquivados" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} className="text-muted" />
                </div>
              )}
            </div>

            {list.isLoading ? (
              <div className="space-y-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-16" />)}</div>
            ) : list.error ? (
              <Card className="p-6 text-sm text-danger" role="alert">{errorMessage(list.error)}</Card>
            ) : items.length === 0 ? (
              <EmptyState
                icon={<FileText className="h-9 w-9" aria-hidden />}
                title={debounced || showArchived ? "Nenhum modelo encontrado" : "Nenhum modelo ainda"}
                description={debounced || showArchived ? "Tente outra busca." : "Envie um documento .docx que você já usa para criar o primeiro."}
                action={!debounced && !showArchived ? <Link href="/generators/new"><Button variant="primary"><FilePlus2 className="h-4 w-4" aria-hidden /> Novo modelo</Button></Link> : undefined}
              />
            ) : (
              <Card className="overflow-x-auto">
                <table className="w-full min-w-[720px] text-left text-sm">
                  <caption className="sr-only">Lista de modelos</caption>
                  <thead className="border-b border-border bg-surface-2 text-xs uppercase tracking-wide text-muted">
                    <tr>
                      <th scope="col" className="w-10 px-2 py-3"><span className="sr-only">Fixar</span></th>
                      <th scope="col" className="px-2 py-3 font-semibold">Modelo</th>
                      <th scope="col" className="px-4 py-3 text-right font-semibold">Campos</th>
                      <th scope="col" className="px-4 py-3 text-right font-semibold">Gerados</th>
                      <th scope="col" className="px-4 py-3 font-semibold">Atualizado</th>
                      <th scope="col" className="px-2 py-3"><span className="sr-only">Ações</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((g) => (
                      <tr key={g.id} className="border-b border-border last:border-0 hover:bg-surface-2/60">
                        <td className="px-2 py-2"><PinButton pinned={g.is_pinned} onToggle={() => togglePin(g)} /></td>
                        <td className="px-2 py-3">
                          <div className="flex items-center gap-2.5">
                            <ModelAvatar name={g.name} size="sm" />
                            <div className="min-w-0">
                              <Link href={openHref(g)} className="font-medium hover:text-primary hover:underline">{g.name}</Link>
                              <p className="line-clamp-1 max-w-md text-xs text-muted">
                                {g.status === "archived" && <Badge className="mr-1 align-middle">Arquivado</Badge>}
                                {!g.has_template ? "Falta enviar o documento .docx" : g.description || "Sem descrição"}
                              </p>
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums">{g.fields_count}</td>
                        <td className="px-4 py-3 text-right tabular-nums">{g.documents_generated}</td>
                        <td className="px-4 py-3 text-muted">{timeAgo(g.updated_at)}</td>
                        <td className="px-2 py-3">
                          <div className="flex items-center justify-end gap-1">
                            {g.has_template && <Link href={`/generators/${g.id}/use`}><Button size="sm" variant="ghost" className="text-primary"><Play className="h-3.5 w-3.5" aria-hidden /> Preencher</Button></Link>}
                            <ActionMenu label={`Ações de ${g.name}`} items={menuFor(g)} />
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            )}
          </section>
        </>
      ) : null}

      <ConfirmDialog
        open={!!toDelete}
        onOpenChange={(o) => !o && setToDelete(null)}
        title="Excluir modelo?"
        description={toDelete ? `“${toDelete.name}” deixará de aparecer nas suas listas. O histórico de gerações já feitas é mantido.` : undefined}
        confirmLabel="Excluir modelo"
        danger
        loading={act.isPending}
        onConfirm={() => toDelete && act.mutate({ kind: "delete", g: toDelete })}
      />
    </AppShell>
  );
}
