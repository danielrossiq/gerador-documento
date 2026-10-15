"use client";

import { ArrowLeft, Check, FileText, Layers } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type GeneratorStep = "template" | "fields" | "review" | "generate";

type StepDef = { key: GeneratorStep; label: string; href: string; done: boolean; blocked: string | null };

export function stepHrefs(id: string) {
  return {
    template: `/generators/${id}/template`,
    fields: `/generators/${id}/edit`,
    review: `/generators/${id}/review`,
    generate: `/generators/${id}/use`,
    batch: `/generators/${id}/batch`,
  };
}

/** Para onde levar alguém que abre o modelo: a próxima etapa que falta, ou a geração se já está tudo pronto. */
export function nextHref(g: { id: string; has_template: boolean; fields_count: number }): string {
  const h = stepHrefs(g.id);
  if (!g.has_template) return h.template;
  if (g.fields_count === 0) return h.fields;
  return h.generate;
}

/**
 * Etapas do modelo: Documento → Campos → Revisão → Gerar. Mostra onde a pessoa está (aria-current="step"), o que já
 * foi feito (✓) e bloqueia, com explicação, as etapas que ainda não fazem sentido (ex.: gerar sem nenhum campo).
 */
export function GeneratorSteps({ id, current, hasTemplate, fieldsCount, onNavigate, compact, className }: {
  id: string;
  current: GeneratorStep;
  hasTemplate: boolean;
  fieldsCount: number;
  /** O editor precisa salvar antes de sair; quando informado, intercepta a navegação. */
  onNavigate?: (href: string) => void;
  compact?: boolean;
  className?: string;
}) {
  const h = stepHrefs(id);
  const needDoc = hasTemplate ? null : "Envie o documento primeiro";
  const needFields = needDoc ?? (fieldsCount > 0 ? null : "Crie pelo menos um campo primeiro");
  const steps: StepDef[] = [
    { key: "template", label: "Documento", href: h.template, done: hasTemplate, blocked: null },
    { key: "fields", label: "Campos", href: h.fields, done: fieldsCount > 0, blocked: needDoc },
    { key: "review", label: "Revisão", href: h.review, done: false, blocked: needFields },
    { key: "generate", label: "Gerar", href: h.generate, done: false, blocked: needFields },
  ];
  const currentIdx = steps.findIndex((s) => s.key === current);

  return (
    <nav aria-label="Etapas do modelo" className={cn("min-w-0", className)}>
      <ol className="flex items-center gap-1 sm:gap-2">
        {steps.map((s, i) => {
          const isCurrent = s.key === current;
          const circle = (
            <span
              aria-hidden
              className={cn(
                "grid h-6 w-6 shrink-0 place-items-center rounded-full border text-xs font-bold",
                isCurrent ? "border-primary bg-primary text-primary-fg" : s.done ? "border-success bg-success-soft text-success" : "border-border-strong bg-surface text-muted",
              )}
            >
              {s.done && !isCurrent ? <Check className="h-3.5 w-3.5" /> : i + 1}
            </span>
          );
          const text = (
            <span className={cn("whitespace-nowrap", compact ? "text-xs sm:text-sm" : "text-sm", isCurrent ? "font-semibold text-fg" : "text-muted")}>
              {s.label}
              <span className="sr-only">{isCurrent ? " (etapa atual)" : s.done ? " (concluída)" : s.blocked ? ` (indisponível: ${s.blocked})` : ""}</span>
            </span>
          );
          const cls = cn("flex items-center gap-1.5 rounded-md px-1.5 py-1", !isCurrent && !s.blocked && "hover:bg-surface-2");
          let node: ReactNode;
          if (isCurrent) node = <span aria-current="step" className={cls}>{circle}{text}</span>;
          else if (s.blocked) node = <span aria-disabled="true" title={s.blocked} className={cn(cls, "cursor-not-allowed opacity-60")}>{circle}{text}</span>;
          else if (onNavigate) node = <button type="button" className={cls} onClick={() => onNavigate(s.href)}>{circle}{text}</button>;
          else node = <Link href={s.href} className={cls}>{circle}{text}</Link>;
          return (
            <li key={s.key} className="flex min-w-0 items-center gap-1 sm:gap-2">
              {node}
              {i < steps.length - 1 && <span aria-hidden className={cn("hidden h-px w-4 sm:block lg:w-8", i < currentIdx ? "bg-primary/50" : "bg-border-strong")} />}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** Na etapa "Gerar": um documento (formulário) ou vários (planilha). */
export function GenerateModeTabs({ id, current }: { id: string; current: "use" | "batch" }) {
  const h = stepHrefs(id);
  const items = [
    { key: "use", label: "Um documento", sub: "formulário", href: h.generate, icon: FileText },
    { key: "batch", label: "Vários documentos", sub: "planilha", href: h.batch, icon: Layers },
  ] as const;
  return (
    <nav aria-label="Como gerar" className="inline-flex max-w-full rounded-lg border border-border bg-surface-2 p-0.5">
      {items.map(({ key, label, sub, href, icon: Icon }) => {
        const active = key === current;
        const cls = cn("flex h-9 items-center gap-1.5 rounded-md px-3 text-sm font-medium whitespace-nowrap transition-colors", active ? "bg-surface text-fg shadow-sm" : "text-muted hover:text-fg");
        const body = (
          <>
            <Icon className="h-4 w-4" aria-hidden />
            {label}
            <span className="hidden text-xs font-normal text-muted md:inline">({sub})</span>
          </>
        );
        return active ? <span key={key} aria-current="page" className={cls}>{body}</span> : <Link key={key} href={href} className={cls} data-testid={`mode-${key}`}>{body}</Link>;
      })}
    </nav>
  );
}

/** Cabeçalho comum das telas de um modelo (exceto o editor, que tem layout de tela cheia). */
export function GeneratorHeader({ id, name, step, hasTemplate, fieldsCount, description, actions, children }: {
  id: string;
  name: string;
  step: GeneratorStep;
  hasTemplate: boolean;
  fieldsCount: number;
  description?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="mb-6 space-y-4">
      <div>
        <Link href="/models" className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg">
          <ArrowLeft className="h-4 w-4" aria-hidden /> Modelos
        </Link>
        <div className="mt-1 flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="break-words text-2xl font-bold tracking-tight">{name}</h1>
            {description && <p className="mt-1 text-sm text-muted">{description}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-y border-border py-2">
        <GeneratorSteps id={id} current={step} hasTemplate={hasTemplate} fieldsCount={fieldsCount} />
        {children}
      </div>
    </div>
  );
}
