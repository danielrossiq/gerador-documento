"use client";

import { FileText, Layers, PencilRuler, Settings2 } from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";

type Item = { key: string; label: string; short: string; href: string; icon: typeof FileText };

function Segmented({ items, current, ariaLabel, onNavigate, className }: {
  items: Item[];
  current: string;
  ariaLabel: string;
  onNavigate?: (href: string) => void;
  className?: string;
}) {
  return (
    <nav aria-label={ariaLabel} className={cn("inline-flex rounded-lg border border-border bg-surface-2 p-0.5", className)}>
      {items.map(({ key, label, short, href, icon: Icon }) => {
        const active = key === current;
        const cls = cn(
          "flex h-8 items-center gap-1.5 rounded-md px-3 text-sm font-medium whitespace-nowrap transition-colors",
          active ? "bg-surface text-fg shadow-sm" : "text-muted hover:text-fg",
        );
        const body = (
          <>
            <Icon className="h-4 w-4" aria-hidden />
            {short === label ? (
              <span>{label}</span>
            ) : (
              <>
                <span className="hidden sm:inline">{label}</span>
                <span className="sm:hidden">{short}</span>
              </>
            )}
          </>
        );
        if (active) return <span key={key} aria-current="page" className={cls}>{body}</span>;
        return onNavigate ? (
          <button key={key} type="button" className={cls} onClick={() => onNavigate(href)}>{body}</button>
        ) : (
          <Link key={key} href={href} className={cls}>{body}</Link>
        );
      })}
    </nav>
  );
}

export type ModelMode = "use" | "batch" | "edit";

/** As três formas de trabalhar com um modelo, sempre à mão — antes cada tela era um beco sem saída. */
export function ModelNav({ id, current, onNavigate, className }: {
  id: string;
  current: ModelMode;
  /** O editor precisa salvar antes de sair; quando informado, intercepta o clique. */
  onNavigate?: (href: string) => void;
  className?: string;
}) {
  const items: Item[] = [
    { key: "use", label: "Preencher", short: "Preencher", href: `/generators/${id}/use`, icon: FileText },
    { key: "batch", label: "Em lote (planilha)", short: "Em lote", href: `/generators/${id}/batch`, icon: Layers },
    { key: "edit", label: "Editar campos", short: "Editar", href: `/generators/${id}/edit`, icon: PencilRuler },
  ];
  return <Segmented items={items} current={current} ariaLabel="Modos do modelo" onNavigate={onNavigate} className={className} />;
}

export function KitNav({ id, current, className }: { id: string; current: "use" | "edit"; className?: string }) {
  const items: Item[] = [
    { key: "use", label: "Preencher kit", short: "Preencher", href: `/kits/${id}/use`, icon: FileText },
    { key: "edit", label: "Configurar", short: "Configurar", href: `/kits/${id}/edit`, icon: Settings2 },
  ];
  return <Segmented items={items} current={current} ariaLabel="Modos do kit" className={className} />;
}
