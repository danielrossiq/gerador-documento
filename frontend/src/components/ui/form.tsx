"use client";

import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const CONTROL =
  "w-full rounded-md border border-border-strong bg-surface px-3 text-sm text-fg placeholder:text-muted " +
  "disabled:opacity-60 aria-[invalid=true]:border-danger aria-[invalid=true]:bg-danger-soft";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...p }, ref) {
  return <input ref={ref} className={cn(CONTROL, "h-10", className)} {...p} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...p }, ref) {
  return <textarea ref={ref} className={cn(CONTROL, "min-h-24 py-2", className)} {...p} />;
});

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className, children, ...p }, ref) {
  return (
    <select ref={ref} className={cn(CONTROL, "h-10 pr-8", className)} {...p}>
      {children}
    </select>
  );
});

export function Checkbox({ label, className, ...p }: InputHTMLAttributes<HTMLInputElement> & { label: ReactNode }) {
  const id = useId();
  return (
    <label htmlFor={p.id ?? id} className={cn("flex cursor-pointer items-start gap-2 text-sm", className)}>
      <input id={p.id ?? id} type="checkbox" className="mt-0.5 h-4 w-4 accent-[var(--primary)]" {...p} />
      <span>{label}</span>
    </label>
  );
}

/**
 * Campo de formulário acessível: rótulo associado, ajuda e erro em TEXTO (não só cor), ligados por aria-describedby.
 * O filho recebe id/aria via render-prop para ficar sempre associado.
 */
export function Field({
  label, help, error, required, children, className, hideLabel,
}: {
  label: string;
  help?: string | null;
  error?: string | null;
  required?: boolean;
  hideLabel?: boolean;
  className?: string;
  children: (a: { id: string; "aria-describedby"?: string; "aria-invalid"?: boolean; "aria-required"?: boolean }) => ReactNode;
}) {
  const id = useId();
  const helpId = help ? `${id}-help` : undefined;
  const errId = error ? `${id}-err` : undefined;
  const describedby = [helpId, errId].filter(Boolean).join(" ") || undefined;
  return (
    <div className={cn("space-y-1.5", className)}>
      <label htmlFor={id} className={cn("block text-sm font-medium", hideLabel && "sr-only")}>
        {label}
        {required && (
          <span aria-hidden className="ml-0.5 text-danger">
            *
          </span>
        )}
        {required && <span className="sr-only"> (obrigatório)</span>}
      </label>
      {children({ id, "aria-describedby": describedby, "aria-invalid": error ? true : undefined, "aria-required": required || undefined })}
      {help && !error && (
        <p id={helpId} className="text-xs text-muted">
          {help}
        </p>
      )}
      {error && (
        <p id={errId} role="alert" className="flex items-start gap-1 text-xs font-medium text-danger">
          <span aria-hidden>⚠</span>
          <span>{error}</span>
        </p>
      )}
    </div>
  );
}
