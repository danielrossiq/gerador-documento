"use client";

import { AlertTriangle, ArrowDown, ArrowUp, ChevronLeft, ChevronRight, ListTree, Plus, Search, Type } from "lucide-react";
import { useMemo, useState } from "react";
import type { OutlineItem } from "@/components/editor/doc-utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/form";
import { Tabs, TabPanel } from "@/components/ui/tabs";
import { FIELD_TYPE_META } from "@/lib/fields/meta";
import type { FieldOut } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Barra lateral esquerda recolhível: lista de campos, estrutura do documento e busca no texto. */
export function LeftSidebar({
  collapsed, onToggle, fields, selectedId, onSelect, onInsert, onMove, outline, onGoOutline, search, onSearch, matches, matchIndex, onMatchNav,
}: {
  collapsed: boolean;
  onToggle: () => void;
  fields: FieldOut[];
  selectedId: string | null;
  onSelect: (f: FieldOut) => void;
  onInsert: (f: FieldOut) => void;
  onMove: (id: string, dir: -1 | 1) => void;
  outline: OutlineItem[];
  onGoOutline: (o: OutlineItem) => void;
  search: string;
  onSearch: (q: string) => void;
  matches: number;
  matchIndex: number;
  onMatchNav: (d: -1 | 1) => void;
}) {
  const [tab, setTab] = useState("fields");
  const [q, setQ] = useState("");
  const filtered = useMemo(() => fields.filter((f) => f.label.toLowerCase().includes(q.toLowerCase()) || f.name.includes(q.toLowerCase())), [fields, q]);

  if (collapsed) {
    return (
      <aside aria-label="Campos e estrutura (recolhida)" className="flex w-10 shrink-0 flex-col items-center border-r border-border bg-surface py-2">
        <Button size="icon" variant="ghost" aria-label="Expandir barra lateral" onClick={onToggle}>
          <ChevronRight className="h-4 w-4" aria-hidden />
        </Button>
        <span className="mt-3 rotate-90 whitespace-nowrap text-xs text-muted">{fields.length} campos</span>
      </aside>
    );
  }

  return (
    <aside aria-label="Campos e estrutura" className="flex w-72 shrink-0 flex-col border-r border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <h2 className="text-sm font-semibold">Documento</h2>
        <Button size="icon" variant="ghost" aria-label="Recolher barra lateral" onClick={onToggle}>
          <ChevronLeft className="h-4 w-4" aria-hidden />
        </Button>
      </div>
      <Tabs
        value={tab}
        onValueChange={setTab}
        className="flex min-h-0 flex-1 flex-col"
        tabs={[{ value: "fields", label: `Campos (${fields.length})` }, { value: "outline", label: "Estrutura" }, { value: "search", label: "Buscar" }]}
      >
        <TabPanel value="fields" className="min-h-0 flex-1 overflow-y-auto p-3">
          <div className="relative mb-3">
            <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted" aria-hidden />
            <Input aria-label="Buscar campo" placeholder="Buscar campo" className="pl-9" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          {fields.length === 0 ? (
            <p className="rounded-md border border-dashed border-border-strong p-4 text-center text-sm text-muted">
              Nenhum campo ainda. Selecione um texto no documento e escolha <strong>Transformar em campo</strong>.
            </p>
          ) : (
            <ul className="space-y-1.5" aria-label="Campos do modelo">
              {filtered.map((f) => {
                const Icon = FIELD_TYPE_META[f.type]?.icon ?? Type;
                const idx = fields.findIndex((x) => x.id === f.id);
                return (
                  <li key={f.id} className={cn("group rounded-md border p-2", selectedId === f.id ? "border-primary bg-primary-soft" : "border-border bg-surface")}>
                    <button type="button" onClick={() => onSelect(f)} className="flex w-full items-start gap-2 text-left" aria-current={selectedId === f.id || undefined}>
                      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">{f.label}</span>
                        <span className="block text-xs text-muted">
                          {FIELD_TYPE_META[f.type]?.label}
                          {f.required ? " · obrigatório" : ""}
                        </span>
                        {f.missing_in_document ? (
                          <span className="mt-0.5 flex items-center gap-1 text-xs font-medium text-warning">
                            <AlertTriangle className="h-3 w-3" aria-hidden /> Não está no documento
                          </span>
                        ) : (
                          <span className="text-xs text-muted">{f.occurrences}× no documento</span>
                        )}
                      </span>
                    </button>
                    <div className="mt-1 flex items-center gap-0.5">
                      <Button size="sm" variant="ghost" onClick={() => onInsert(f)} aria-label={`Inserir ${f.label} no cursor`} title="Inserir no cursor">
                        <Plus className="h-3.5 w-3.5" aria-hidden /> Inserir
                      </Button>
                      <span className="ml-auto flex">
                        <Button size="icon" variant="ghost" aria-label={`Subir ${f.label} no formulário`} disabled={idx === 0 || !!q} onClick={() => onMove(f.id, -1)} className="h-7 w-7">
                          <ArrowUp className="h-3.5 w-3.5" aria-hidden />
                        </Button>
                        <Button size="icon" variant="ghost" aria-label={`Descer ${f.label} no formulário`} disabled={idx === fields.length - 1 || !!q} onClick={() => onMove(f.id, 1)} className="h-7 w-7">
                          <ArrowDown className="h-3.5 w-3.5" aria-hidden />
                        </Button>
                      </span>
                    </div>
                  </li>
                );
              })}
              {filtered.length === 0 && <li className="text-sm text-muted">Nenhum campo com “{q}”.</li>}
            </ul>
          )}
          <p className="mt-3 text-xs text-muted">A ordem da lista é a ordem do formulário. Use as setas para reordenar.</p>
        </TabPanel>

        <TabPanel value="outline" className="min-h-0 flex-1 overflow-y-auto p-3">
          {outline.length === 0 ? (
            <p className="text-sm text-muted">Sem títulos ou tabelas detectados.</p>
          ) : (
            <ul aria-label="Estrutura do documento" className="space-y-0.5">
              {outline.map((o) => (
                <li key={o.key}>
                  <button
                    type="button"
                    onClick={() => onGoOutline(o)}
                    className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-surface-2"
                    style={{ paddingLeft: 8 + Math.max(0, o.level - (o.kind === "part" ? 0 : 1)) * 12 }}
                  >
                    <ListTree className={cn("h-3.5 w-3.5 shrink-0", o.kind === "part" ? "text-primary" : "text-muted")} aria-hidden />
                    <span className={cn("truncate", o.kind === "part" && "font-semibold")}>{o.label}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </TabPanel>

        <TabPanel value="search" className="min-h-0 flex-1 overflow-y-auto p-3">
          <label htmlFor="doc-search" className="mb-1 block text-sm font-medium">
            Pesquisar no documento
          </label>
          <Input id="doc-search" value={search} onChange={(e) => onSearch(e.target.value)} placeholder="Digite ao menos 2 letras" />
          <div className="mt-2 flex items-center justify-between text-sm" aria-live="polite">
            <span className="text-muted">{search.trim().length < 2 ? "" : matches ? `${matchIndex + 1} de ${matches}` : "Nenhum resultado"}</span>
            <span className="flex">
              <Button size="icon" variant="ghost" aria-label="Resultado anterior" disabled={!matches} onClick={() => onMatchNav(-1)}>
                <ChevronLeft className="h-4 w-4" aria-hidden />
              </Button>
              <Button size="icon" variant="ghost" aria-label="Próximo resultado" disabled={!matches} onClick={() => onMatchNav(1)}>
                <ChevronRight className="h-4 w-4" aria-hidden />
              </Button>
            </span>
          </div>
        </TabPanel>
      </Tabs>
    </aside>
  );
}
