"use client";

import { ChevronLeft, ChevronRight, ListTree, X } from "lucide-react";
import { useState } from "react";
import type { OutlineItem } from "@/components/editor/doc-utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/form";
import { Tabs, TabPanel } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

/**
 * Painel opcional para navegar em documentos longos: buscar no texto e pular para títulos/tabelas.
 * A lista de campos saiu daqui e foi para o painel da direita, junto da configuração de cada campo.
 */
export function DocNavigator({ onClose, outline, onGoOutline, search, onSearch, matches, matchIndex, onMatchNav }: {
  onClose: () => void;
  outline: OutlineItem[];
  onGoOutline: (o: OutlineItem) => void;
  search: string;
  onSearch: (q: string) => void;
  matches: number;
  matchIndex: number;
  onMatchNav: (d: -1 | 1) => void;
}) {
  const [tab, setTab] = useState("search");
  return (
    <aside aria-label="Navegar no documento" className="flex w-72 shrink-0 flex-col border-r border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <h2 className="text-sm font-semibold">Navegar no documento</h2>
        <Button size="icon" variant="ghost" aria-label="Fechar navegação" onClick={onClose}>
          <X className="h-4 w-4" aria-hidden />
        </Button>
      </div>
      <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col" tabs={[{ value: "search", label: "Buscar" }, { value: "outline", label: "Estrutura" }]}>
        <TabPanel value="search" className="min-h-0 flex-1 overflow-y-auto p-3">
          <label htmlFor="doc-search" className="mb-1 block text-sm font-medium">
            Procurar um trecho
          </label>
          <Input id="doc-search" autoFocus value={search} onChange={(e) => onSearch(e.target.value)} placeholder="Digite ao menos 2 letras" onKeyDown={(e) => e.key === "Enter" && onMatchNav(e.shiftKey ? -1 : 1)} />
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
          <p className="mt-3 text-xs text-muted">Dica: ache o trecho, selecione-o no documento e transforme em campo.</p>
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
      </Tabs>
    </aside>
  );
}
