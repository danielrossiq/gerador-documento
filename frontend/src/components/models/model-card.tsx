"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, ClipboardCheck, Copy, FileUp, Layers, PencilRuler, Pin, Play, Star, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { nextHref, stepHrefs } from "@/components/generators/steps";
import { ButtonLink } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { ActionMenu, type MenuItem } from "@/components/ui/menu";
import { Badge, Card } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import type { GeneratorOut } from "@/lib/types";
import { cn, plural, timeAgo } from "@/lib/utils";

const AVATAR_TONES = ["bg-primary-soft text-primary", "bg-success-soft text-success", "bg-warning-soft text-warning", "bg-danger-soft text-danger"] as const;

function avatarClass(name: string): string {
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return AVATAR_TONES[h % AVATAR_TONES.length];
}

export function ModelAvatar({ name, className }: { name: string; className?: string }) {
  const letter = (name.trim()[0] ?? "?").toUpperCase();
  return (
    <span aria-hidden className={cn("grid h-10 w-10 shrink-0 place-items-center rounded-full text-base font-bold", avatarClass(name), className)}>
      {letter}
    </span>
  );
}

export function PinButton({ pinned, name, onToggle }: { pinned: boolean; name: string; onToggle: () => void }) {
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

export const isReady = (g: GeneratorOut) => g.has_template && g.fields_count > 0;

/** Em que pé está o modelo e qual é a próxima ação — a mesma lógica das etapas Documento → Campos → Revisão → Gerar. */
export function statusOf(g: GeneratorOut) {
  const h = stepHrefs(g.id);
  if (!g.has_template) return { tone: "warning" as const, label: "Falta o documento", hint: "Envie o documento (.docx ou PDF) para começar.", action: { label: "Enviar documento", href: h.template, icon: FileUp } };
  if (g.fields_count === 0) {
    const analysing = g.analysis_status === "pending" || g.analysis_status === "running";
    return { tone: "warning" as const, label: analysing ? "Analisando…" : "Sem campos", hint: "Marque no documento o que muda de um para outro.", action: { label: "Criar campos", href: h.fields, icon: PencilRuler } };
  }
  return { tone: "success" as const, label: "Pronto para gerar", hint: null, action: { label: "Preencher", href: h.generate, icon: Play } };
}

/** Ações do menu "⋯" de um modelo (fixar, duplicar, arquivar, excluir…) + o diálogo de exclusão. */
export function useModelActions() {
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useToast();
  const [toDelete, setToDelete] = useState<GeneratorOut | null>(null);

  const act = useMutation({
    mutationFn: async (a: { kind: "duplicate" | "archive" | "unarchive" | "delete" | "pin" | "unpin"; g: GeneratorOut }) => {
      if (a.kind === "delete") return api.delete<undefined>(`/generators/${a.g.id}`);
      return api.post<GeneratorOut | undefined>(`/generators/${a.g.id}/${a.kind}`);
    },
    onSuccess: (res, v) => {
      qc.invalidateQueries({ queryKey: ["generators"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      setToDelete(null);
      if (v.kind === "duplicate") toast.push({ tone: "success", title: "Cópia criada", description: res && "name" in res ? `“${res.name}” já está na lista, pronta para ajustar.` : undefined });
      const msg = { archive: "Modelo arquivado.", unarchive: "Modelo restaurado.", delete: "Modelo excluído.", pin: "", unpin: "", duplicate: "" }[v.kind];
      if (msg) toast.push({ tone: "success", title: msg });
    },
    onError: (e) => toast.push({ tone: "danger", title: "Não foi possível concluir", description: errorMessage(e) }),
  });
  const togglePin = (g: GeneratorOut) => act.mutate({ kind: g.is_pinned ? "unpin" : "pin", g });

  function menuFor(g: GeneratorOut): MenuItem[] {
    const h = stepHrefs(g.id);
    const ready = isReady(g);
    return [
      { label: "Preencher um documento", icon: <Play className="h-4 w-4" aria-hidden />, onSelect: () => router.push(h.generate), disabled: !ready },
      { label: "Gerar vários (planilha)", icon: <Layers className="h-4 w-4" aria-hidden />, onSelect: () => router.push(h.batch), disabled: !ready },
      { separator: true },
      { label: g.has_template ? "Trocar o documento" : "Enviar o documento", icon: <FileUp className="h-4 w-4" aria-hidden />, onSelect: () => router.push(h.template) },
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

  const deleteDialog = (
    <ConfirmDialog
      open={!!toDelete}
      onOpenChange={(o) => !o && setToDelete(null)}
      title="Excluir modelo?"
      description={toDelete ? `“${toDelete.name}” deixará de aparecer nas suas listas. O histórico de documentos já gerados é mantido.` : undefined}
      confirmLabel="Excluir modelo"
      danger
      loading={act.isPending}
      onConfirm={() => toDelete && act.mutate({ kind: "delete", g: toDelete })}
    />
  );

  return { menuFor, togglePin, deleteDialog };
}

/** Cartão de um modelo: status, próxima ação e atalho para o lote. */
export function ModelCard({ g, menu, onTogglePin }: { g: GeneratorOut; menu: MenuItem[]; onTogglePin: () => void }) {
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
            <ButtonLink href={stepHrefs(g.id).batch} size="sm" title="Vários documentos de uma vez, a partir de uma planilha" aria-label={`Gerar em lote com ${g.name}`}>
              <Layers className="h-3.5 w-3.5" aria-hidden /> Em lote
            </ButtonLink>
          )}
          <ActionMenu label={`Mais ações de ${g.name}`} items={menu} />
        </div>
      </Card>
    </li>
  );
}
