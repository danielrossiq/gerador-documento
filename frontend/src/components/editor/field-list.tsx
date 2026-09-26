"use client";

import { AlertTriangle, ArrowDown, ArrowUp, ListOrdered, MousePointerClick, Plus, Sparkles, Type } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/misc";
import type { FieldIssue } from "@/lib/fields/issues";
import { FIELD_TYPE_META } from "@/lib/fields/meta";
import type { FieldOut } from "@/lib/types";
import { cn, plural } from "@/lib/utils";

/**
 * Lista dos campos do gerador (painel direito do editor). A ordem é a do formulário; por padrão ela acompanha a
 * ordem em que os campos aparecem no documento. Cada campo mostra onde está e o que falta configurar.
 */
export function FieldList({ fields, issues, selectedId, inDocOrder, suggestions, onSelect, onInsert, onMove, onSyncOrder, onShowSuggestions }: {
  fields: FieldOut[];
  issues: Record<string, FieldIssue[]>;
  selectedId: string | null;
  inDocOrder: boolean;
  suggestions: number;
  onSelect: (f: FieldOut) => void;
  onInsert: (f: FieldOut) => void;
  onMove: (id: string, dir: -1 | 1) => void;
  onSyncOrder: () => void;
  onShowSuggestions: () => void;
}) {
  const withIssues = fields.filter((f) => issues[f.id]?.length);
  const errors = withIssues.filter((f) => issues[f.id].some((i) => i.severity === "error")).length;

  if (fields.length === 0) {
    return (
      <div className="space-y-4 text-sm" data-testid="fields-empty">
        <div className="rounded-md border border-dashed border-border-strong p-4">
          <p className="flex items-center gap-2 font-semibold"><MousePointerClick className="h-4 w-4 text-primary" aria-hidden /> Nenhum campo ainda</p>
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-muted">
            <li>Selecione no documento um trecho que muda de um documento para outro (ex.: um nome).</li>
            <li>Clique em <strong className="text-fg">Transformar em campo</strong> no menu que aparece.</li>
            <li>Dê um nome ao campo — ele vira uma pergunta no formulário.</li>
          </ol>
          <p className="mt-2 text-xs text-muted">
            Atalho: <kbd className="rounded border border-border px-1">Ctrl</kbd>+<kbd className="rounded border border-border px-1">Shift</kbd>+<kbd className="rounded border border-border px-1">F</kbd>
          </p>
        </div>
        {suggestions > 0 && (
          <div className="rounded-md bg-primary-soft p-3">
            <p className="text-fg"><Sparkles className="mr-1 inline h-4 w-4 text-primary" aria-hidden />Encontramos {plural(suggestions, "trecho que parece mudar", "trechos que parecem mudar")}.</p>
            <Button size="sm" variant="primary" className="mt-2" onClick={onShowSuggestions}>Ver sugestões</Button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {withIssues.length > 0 ? (
        <div role="status" className={cn("rounded-md border p-3 text-sm", errors ? "border-danger/30 bg-danger-soft" : "border-warning/30 bg-warning-soft")} data-testid="fields-issues">
          <p className="flex items-center gap-1.5 font-semibold text-fg">
            <AlertTriangle className={cn("h-4 w-4", errors ? "text-danger" : "text-warning")} aria-hidden />
            {plural(withIssues.length, "campo precisa", "campos precisam")} de atenção
          </p>
          <p className="mt-0.5 text-xs text-muted">Clique no campo marcado com ⚠ para ver o que ajustar.</p>
        </div>
      ) : (
        <p className="rounded-md border border-success/30 bg-success-soft p-2.5 text-sm text-fg" role="status">
          {plural(fields.length, "campo configurado", "campos configurados")}, sem pendências.
        </p>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
        <span>{inDocOrder ? "Mesma ordem do documento (é a ordem do formulário)." : "Ordem personalizada do formulário."}</span>
        {!inDocOrder && (
          <Button size="sm" variant="ghost" onClick={onSyncOrder} className="h-7 px-2 text-xs">
            <ListOrdered className="h-3.5 w-3.5" aria-hidden /> Seguir a ordem do documento
          </Button>
        )}
      </div>

      <ul className="space-y-1.5" aria-label="Campos do gerador (na ordem do formulário)" data-testid="field-list">
        {fields.map((f, idx) => {
          const Icon = FIELD_TYPE_META[f.type]?.icon ?? Type;
          const fi = issues[f.id] ?? [];
          const bad = fi.some((i) => i.severity === "error");
          const selected = selectedId === f.id;
          return (
            <li key={f.id} className={cn("rounded-md border p-2", selected ? "border-primary bg-primary-soft" : fi.length ? (bad ? "border-danger/40" : "border-warning/40") : "border-border bg-surface")} data-testid="field-item">
              <div className="flex items-start gap-1">
                <button type="button" onClick={() => onSelect(f)} className="flex min-w-0 flex-1 items-start gap-2 rounded text-left" aria-current={selected || undefined}>
                  <Icon className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1 text-sm font-medium">
                      <span className="truncate">{f.label}</span>
                      {f.required && <span className="text-danger" aria-label="obrigatório">*</span>}
                    </span>
                    <span className="block text-xs text-muted">
                      {FIELD_TYPE_META[f.type]?.label}
                      {f.type === "select" ? ` · ${plural(f.options.length, "opção", "opções")}` : ""}
                      {f.occurrences > 0 ? ` · ${f.occurrences}× no documento` : ""}
                    </span>
                    {fi.length > 0 && (
                      <span className={cn("mt-0.5 flex items-start gap-1 text-xs font-medium", bad ? "text-danger" : "text-warning")}>
                        <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                        <span>{fi[0].kind === "duplicate_label" ? "Nome repetido" : fi[0].kind === "empty_options" ? "Lista sem opções" : fi[0].kind === "not_in_document" ? "Fora do documento" : "Sem nome"}{fi.length > 1 ? ` (+${fi.length - 1})` : ""}</span>
                      </span>
                    )}
                  </span>
                </button>
                <span className="flex shrink-0 items-center">
                  <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => onInsert(f)} aria-label={`Inserir ${f.label} onde está o cursor`} title="Inserir onde está o cursor no documento">
                    <Plus className="h-3.5 w-3.5" aria-hidden />
                  </Button>
                  <Button size="icon" variant="ghost" className="h-7 w-7" aria-label={`Subir ${f.label} no formulário`} disabled={idx === 0} onClick={() => onMove(f.id, -1)}>
                    <ArrowUp className="h-3.5 w-3.5" aria-hidden />
                  </Button>
                  <Button size="icon" variant="ghost" className="h-7 w-7" aria-label={`Descer ${f.label} no formulário`} disabled={idx === fields.length - 1} onClick={() => onMove(f.id, 1)}>
                    <ArrowDown className="h-3.5 w-3.5" aria-hidden />
                  </Button>
                </span>
              </div>
            </li>
          );
        })}
      </ul>
      {suggestions > 0 && (
        <button type="button" onClick={onShowSuggestions} className="flex w-full items-center gap-2 rounded-md border border-dashed border-primary/40 p-2.5 text-left text-sm text-primary hover:bg-primary-soft">
          <Sparkles className="h-4 w-4" aria-hidden /> {plural(suggestions, "sugestão", "sugestões")} ainda não {suggestions === 1 ? "revisada" : "revisadas"}
          <Badge tone="primary" className="ml-auto">Ver</Badge>
        </button>
      )}
    </div>
  );
}
