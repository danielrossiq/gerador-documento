"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, FilePlus2, Layers, Pencil, Play, Search, Star, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AppShell, PageHeader } from "@/components/layout/app-shell";
import { TrySampleButton } from "@/components/onboarding/samples";
import { ButtonLink } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Checkbox, Input, Select } from "@/components/ui/form";
import { ActionMenu, type MenuItem } from "@/components/ui/menu";
import { Badge, Card, EmptyState, Skeleton } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import type { KitOut, Paged } from "@/lib/types";
import { cn, timeAgo } from "@/lib/utils";

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
      aria-label={pinned ? "Desfixar kit" : "Fixar kit"}
      title={pinned ? "Desfixar" : "Fixar no topo"}
      className={cn("grid h-8 w-8 shrink-0 place-items-center rounded-full", pinned ? "text-warning" : "text-muted hover:bg-surface-2 hover:text-fg")}
    >
      <Star className="h-4 w-4" aria-hidden fill={pinned ? "currentColor" : "none"} />
    </button>
  );
}

export default function KitsPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [sort, setSort] = useState("updated");
  const [toDelete, setToDelete] = useState<KitOut | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 250);
    return () => clearTimeout(t);
  }, [q]);

  const status = showArchived ? "archived" : "";
  const list = useQuery({
    queryKey: ["kits", debounced, status, sort],
    queryFn: () => api.get<Paged<KitOut>>(`/kits?page_size=50&sort=${sort}${debounced ? `&q=${encodeURIComponent(debounced)}` : ""}${status ? `&status=${status}` : ""}`),
  });

  const refresh = () => qc.invalidateQueries({ queryKey: ["kits"] });
  const act = useMutation({
    mutationFn: async (a: { kind: "archive" | "unarchive" | "delete" | "pin" | "unpin"; k: KitOut }) => {
      if (a.kind === "delete") return api.delete(`/kits/${a.k.id}`);
      return api.post(`/kits/${a.k.id}/${a.kind}`);
    },
    onSuccess: (_d, v) => {
      refresh();
      setToDelete(null);
      const msg = { archive: "Kit arquivado.", unarchive: "Kit restaurado.", delete: "Kit excluído." }[v.kind as "archive" | "unarchive" | "delete"];
      if (msg) toast.push({ tone: "success", title: msg });
    },
    onError: (e) => toast.push({ tone: "danger", title: "Não foi possível concluir", description: errorMessage(e) }),
  });
  const togglePin = (k: KitOut) => act.mutate({ kind: k.is_pinned ? "unpin" : "pin", k });

  function menuFor(k: KitOut): MenuItem[] {
    return [
      { label: "Preencher", icon: <Play className="h-4 w-4" aria-hidden />, onSelect: () => router.push(`/kits/${k.id}/use`), disabled: !k.has_documents },
      { label: "Configurar", icon: <Pencil className="h-4 w-4" aria-hidden />, onSelect: () => router.push(`/kits/${k.id}/edit`) },
      { separator: true },
      { label: k.is_pinned ? "Desfixar" : "Fixar no topo", icon: <Star className="h-4 w-4" aria-hidden />, onSelect: () => togglePin(k) },
      k.status === "archived"
        ? { label: "Desarquivar", icon: <ArchiveRestore className="h-4 w-4" aria-hidden />, onSelect: () => act.mutate({ kind: "unarchive", k }) }
        : { label: "Arquivar", icon: <Archive className="h-4 w-4" aria-hidden />, onSelect: () => act.mutate({ kind: "archive", k }) },
      { separator: true },
      { label: "Excluir…", icon: <Trash2 className="h-4 w-4" aria-hidden />, danger: true, onSelect: () => setToDelete(k) },
    ];
  }

  const items = list.data?.items ?? [];

  return (
    <AppShell>
      <PageHeader
        title="Kits"
        description="Um kit junta vários geradores que usam os mesmos dados (nome, CPF, endereço…): você preenche uma vez e recebe todos os documentos."
        actions={
          <ButtonLink href="/kits/new" variant="primary">
            <FilePlus2 className="h-4 w-4" aria-hidden /> Novo kit
          </ButtonLink>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted" aria-hidden />
          <Input aria-label="Buscar kit" placeholder="Buscar" className="w-52 pl-9" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <Select aria-label="Ordenar" value={sort} onChange={(e) => setSort(e.target.value)} className="w-44">
          <option value="updated">Atualização recente</option>
          <option value="name">Nome (A–Z)</option>
          <option value="created">Criação recente</option>
        </Select>
        <Checkbox label="Arquivados" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} className="text-muted" />
      </div>

      {list.isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-40" />)}
        </div>
      ) : list.error ? (
        <Card className="p-6 text-sm text-danger" role="alert">{errorMessage(list.error)}</Card>
      ) : items.length === 0 ? (
        <EmptyState
          icon={<Layers className="h-9 w-9" aria-hidden />}
          title={debounced || showArchived ? "Nenhum kit encontrado" : "Crie seu primeiro kit"}
          description={debounced || showArchived ? "Tente outra busca." : "Contrato + recibo + termo sempre juntos? Num kit você preenche nome, CPF e endereço uma vez e recebe todos os documentos prontos."}
          action={
            !debounced && !showArchived ? (
              <div className="flex flex-wrap justify-center gap-2">
                <ButtonLink href="/kits/new" variant="primary"><FilePlus2 className="h-4 w-4" aria-hidden /> Novo kit</ButtonLink>
                <TrySampleButton kind="kit" />
              </div>
            ) : undefined
          }
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((k) => (
            <Card key={k.id} className={cn("flex flex-col gap-3 p-4", k.is_pinned && "ring-1 ring-warning/40")}>
              <div className="flex items-start gap-3">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-primary-soft text-primary" aria-hidden>
                  <Layers className="h-5 w-5" aria-hidden />
                </span>
                <div className="min-w-0 flex-1">
                  <Link href={k.has_documents ? `/kits/${k.id}/use` : `/kits/${k.id}/edit`} className="font-semibold hover:text-primary hover:underline">{k.name}</Link>
                  <p className="line-clamp-1 text-xs text-muted">{k.description || "Sem descrição"}</p>
                </div>
                <PinButton pinned={k.is_pinned} onToggle={() => togglePin(k)} />
              </div>
              <div className="flex flex-wrap gap-1.5">
                <Badge>{k.items_count} {k.items_count === 1 ? "documento" : "documentos"}</Badge>
                <Badge>{k.fields_count} {k.fields_count === 1 ? "dado em comum" : "dados em comum"}</Badge>
                <Badge tone="success">{k.documents_generated} gerados</Badge>
                {k.status === "archived" && <Badge>Arquivado</Badge>}
              </div>
              <div className="mt-auto flex items-center justify-between gap-2 pt-1">
                <span className="text-xs text-muted">Atualizado {timeAgo(k.updated_at)}</span>
                <div className="flex items-center gap-1.5">
                  {k.has_documents && (
                    <ButtonLink href={`/kits/${k.id}/use`} size="sm" variant="primary">
                      <Play className="h-3.5 w-3.5" aria-hidden /> Preencher
                    </ButtonLink>
                  )}
                  <ActionMenu label={`Ações de ${k.name}`} items={menuFor(k)} />
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={!!toDelete}
        onOpenChange={(o) => !o && setToDelete(null)}
        title="Excluir kit?"
        description={toDelete ? `“${toDelete.name}” deixará de aparecer nas suas listas. Os documentos gerados por ele continuam no histórico.` : undefined}
        confirmLabel="Excluir kit"
        danger
        loading={act.isPending}
        onConfirm={() => toDelete && act.mutate({ kind: "delete", k: toDelete })}
      />
    </AppShell>
  );
}
