"use client";

import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/form";
import { displayFor, liveMask } from "@/lib/fields/masks";
import type { FieldOut } from "@/lib/types";

/**
 * Controle de formulário por tipo de campo, com máscara e rótulo/ajuda/erro acessíveis.
 * O valor é sempre texto no formato de exibição (pt-BR); o servidor normaliza e valida de novo.
 */
export function FieldInput({ field, value, onChange, onBlur, error }: {
  field: FieldOut;
  value: unknown;
  onChange: (v: string | boolean) => void;
  onBlur?: () => void;
  error?: string | null;
}) {
  const f = field;
  const str = value === undefined || value === null ? "" : String(value);
  const help = f.description ?? undefined;
  // o exemplo já aparece como placeholder nos campos de texto; só vira "Ex.:" onde não há placeholder
  const hint = f.example && (f.type === "date" || f.type === "select") ? `Ex.: ${f.example}` : undefined;

  if (f.type === "checkbox") {
    return (
      <div className="space-y-1.5">
        <Checkbox label={<>{f.label}{f.required && <span className="text-danger" aria-hidden> *</span>}</>} checked={value === true} onChange={(e) => onChange(e.target.checked)} onBlur={onBlur} aria-invalid={error ? true : undefined} aria-required={f.required || undefined} data-testid={`field-${f.name}`} />
        {help && <p className="text-xs text-muted">{help}</p>}
        {error && <p role="alert" className="text-xs font-medium text-danger">⚠ {error}</p>}
      </div>
    );
  }

  if (f.type === "yes_no") {
    const id = `yn-${f.name}`;
    return (
      <fieldset aria-describedby={error ? `${id}-err` : undefined} className="space-y-1.5">
        <legend className="text-sm font-medium">
          {f.label}
          {f.required && <span className="text-danger" aria-hidden> *</span>}
          {f.required && <span className="sr-only"> (obrigatório)</span>}
        </legend>
        <div className="flex gap-4">
          {["Sim", "Não"].map((opt) => (
            <label key={opt} className="flex cursor-pointer items-center gap-2 text-sm">
              <input type="radio" name={id} checked={str === opt} onChange={() => onChange(opt)} className="h-4 w-4 accent-[var(--primary)]" data-testid={`field-${f.name}-${opt}`} />
              {opt}
            </label>
          ))}
        </div>
        {help && <p className="text-xs text-muted">{help}</p>}
        {error && <p id={`${id}-err`} role="alert" className="text-xs font-medium text-danger">⚠ {error}</p>}
      </fieldset>
    );
  }

  return (
    <Field label={f.label} help={help ?? hint} error={error} required={f.required}>
      {(a) => {
        const common = { ...a, "data-testid": `field-${f.name}`, onBlur } as const;
        switch (f.type) {
          case "text_long":
            return <Textarea rows={4} placeholder={f.example ?? undefined} value={str} onChange={(e) => onChange(e.target.value)} {...common} />;
          case "select":
            return (
              <Select value={str} onChange={(e) => onChange(e.target.value)} {...common}>
                <option value="">Selecione…</option>
                {f.options.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            );
          case "date":
            return <Input type="date" value={str} onChange={(e) => onChange(e.target.value)} {...common} />;
          case "cpf":
          case "cnpj":
          case "cep":
          case "phone":
            return <Input inputMode={f.type === "cnpj" ? "text" : "numeric"} autoComplete="off" placeholder={f.example ?? undefined} value={str} onChange={(e) => onChange(liveMask(f.type, e.target.value))} {...common} />;
          case "currency":
          case "number":
            return (
              <div className="relative">
                {f.type === "currency" && <span aria-hidden className="pointer-events-none absolute left-3 top-2.5 text-sm text-muted">R$</span>}
                <Input inputMode="decimal" className={f.type === "currency" ? "pl-9" : undefined} placeholder={f.example?.replace(/^R\$\s*/, "") ?? undefined} value={str} onChange={(e) => onChange(e.target.value)} {...common} onBlur={() => { onChange(displayFor({ ...f, default_value: f.default_value }, str)); onBlur?.(); }} />
              </div>
            );
          case "email":
            return <Input type="email" autoComplete="off" placeholder={f.example ?? undefined} value={str} onChange={(e) => onChange(e.target.value)} {...common} />;
          default:
            return <Input placeholder={f.example ?? undefined} value={str} onChange={(e) => onChange(e.target.value)} {...common} />;
        }
      }}
    </Field>
  );
}
