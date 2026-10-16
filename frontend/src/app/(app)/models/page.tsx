"use client";

import { useQuery } from "@tanstack/react-query";
import { FilePlus2, FileText, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { AppShell, PageHeader } from "@/components/layout/app-shell";
import { ModelCard, useModelActions } from "@/components/models/model-card";
import { TrySampleButton } from "@/components/onboarding/samples";
import { ButtonLink } from "@/components/ui/button";
import { Checkbox, Input, Select } from "@/components/ui/form";
import { Card, EmptyState, Skeleton } from "@/components/ui/misc";
import { api, errorMessage } from "@/lib/api";
import type { GeneratorOut, Paged } from "@/lib/types";

/** Todos os modelos, com busca, ordenação e arquivados (a página inicial mostra só os atalhos). */
export default function ModelsPage() {
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [sort, setSort] = useState("updated");
  const { menuFor, togglePin, deleteDialog } = useModelActions();

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 250);
    return () => clearTimeout(t);
  }, [q]);

  const status = showArchived ? "archived" : "";
  const list = useQuery({
    queryKey: ["generators", debounced, status, sort],
    queryFn: () => api.get<Paged<GeneratorOut>>(`/generators?page_size=50&sort=${sort}${debounced ? `&q=${encodeURIComponent(debounced)}` : ""}${status ? `&status=${status}` : ""}`),
  });
  const items = list.data?.items ?? [];
  const filtering = !!debounced || showArchived;

  return (
    <AppShell>
      <PageHeader
        title="Modelos"
        description="Cada modelo transforma um documento que você já usa em um formulário: preencha e baixe o documento pronto — um de cada vez ou vários com uma planilha."
        actions={<ButtonLink href="/generators/new" variant="primary"><FilePlus2 className="h-4 w-4" aria-hidden /> Novo modelo</ButtonLink>}
      />

      <section aria-labelledby="all-h">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 id="all-h" className="text-lg font-semibold">{showArchived ? "Modelos arquivados" : "Seus modelos"}{list.data ? <span className="ml-2 text-sm font-normal text-muted">({list.data.total})</span> : null}</h2>
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted" aria-hidden />
              <Input aria-label="Buscar modelo" placeholder="Buscar" className="w-full pl-9 sm:w-52" value={q} onChange={(e) => setQ(e.target.value)} />
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
            title={filtering ? "Nenhum modelo encontrado" : "Nenhum modelo ainda"}
            description={filtering ? (showArchived ? "Não há modelos arquivados com esse filtro." : "Tente buscar por outra palavra.") : "Envie um documento que você já usa (Word ou PDF digitado) para criar o primeiro."}
            action={
              !filtering ? (
                <div className="flex flex-wrap justify-center gap-2">
                  <ButtonLink href="/generators/new" variant="primary"><FilePlus2 className="h-4 w-4" aria-hidden /> Novo modelo</ButtonLink>
                  <TrySampleButton />
                </div>
              ) : undefined
            }
          />
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-label="Modelos">
            {items.map((g) => <ModelCard key={g.id} g={g} menu={menuFor(g)} onTogglePin={() => togglePin(g)} />)}
          </ul>
        )}
      </section>
      {deleteDialog}
    </AppShell>
  );
}
