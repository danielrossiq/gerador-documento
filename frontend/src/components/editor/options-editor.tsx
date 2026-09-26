"use client";

import { ArrowDown, ArrowUp, ClipboardPaste, Plus, Trash2 } from "lucide-react";
import { useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox, Input, Select, Textarea } from "@/components/ui/form";
import { toSnake } from "@/lib/fields/naming";

export type Opt = { label: string; value?: string };

/** Duplicatas por rótulo ou valor interno (sem diferenciar maiúsculas). Devolve os índices com problema. */
export function duplicateIndexes(options: Opt[]): Set<number> {
  const bad = new Set<number>();
  const labels = new Map<string, number>();
  const values = new Map<string, number>();
  options.forEach((o, i) => {
    const l = o.label.trim().toLowerCase();
    const v = (o.value?.trim() || toSnake(o.label, "opcao")).toLowerCase();
    if (l) {
      if (labels.has(l)) [i, labels.get(l)!].forEach((x) => bad.add(x));
      labels.set(l, i);
      if (values.has(v)) [i, values.get(v)!].forEach((x) => bad.add(x));
      values.set(v, i);
    }
  });
  return bad;
}

/**
 * Editor da lista suspensa: adicionar, renomear, reordenar, remover; colar várias (uma por linha);
 * impede duplicatas; separa rótulo visível de valor interno; define o valor padrão.
 */
export function OptionsEditor({
  options, onChange, defaultValue, onDefaultChange,
}: {
  options: Opt[];
  onChange: (o: Opt[]) => void;
  defaultValue: string;
  onDefaultChange: (v: string) => void;
}) {
  const id = useId();
  const [showValues, setShowValues] = useState(false);
  const [bulk, setBulk] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const last = useRef<HTMLInputElement | null>(null);
  const dups = duplicateIndexes(options);

  const move = (i: number, d: -1 | 1) => {
    const j = i + d;
    if (j < 0 || j >= options.length) return;
    const c = [...options];
    [c[i], c[j]] = [c[j], c[i]];
    onChange(c);
  };
  const update = (i: number, patch: Partial<Opt>) => onChange(options.map((o, k) => (k === i ? { ...o, ...patch } : o)));

  function addBulk() {
    const lines = bulk.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
    const existing = new Set(options.map((o) => o.label.trim().toLowerCase()));
    const fresh: Opt[] = [];
    let skipped = 0;
    for (const l of lines) {
      if (existing.has(l.toLowerCase())) skipped++;
      else {
        existing.add(l.toLowerCase());
        fresh.push({ label: l });
      }
    }
    onChange([...options, ...fresh]);
    setBulk("");
    setNote(`${fresh.length} ${fresh.length === 1 ? "opção adicionada" : "opções adicionadas"}${skipped ? `; ${skipped} repetida(s) ignorada(s)` : ""}.`);
  }

  return (
    <fieldset className="space-y-3 rounded-md border border-border p-3">
      <legend className="px-1 text-sm font-medium">Opções da lista <span className="text-danger" aria-hidden>*</span><span className="sr-only"> (pelo menos uma)</span></legend>
      {options.length === 0 && <p className="text-sm text-warning">Nenhuma opção ainda. Adicione abaixo ou cole várias de uma vez — quem preenche só pode escolher entre elas.</p>}
      <ul className="space-y-2">
        {options.map((o, i) => (
          <li key={i} className="flex items-start gap-1.5">
            <div className="grid flex-1 gap-1.5">
              <Input
                ref={i === options.length - 1 ? last : undefined}
                aria-label={`Opção ${i + 1}`}
                value={o.label}
                aria-invalid={dups.has(i) || undefined}
                onChange={(e) => update(i, { label: e.target.value })}
                className="h-9"
                placeholder="Texto da opção"
              />
              {showValues && <Input aria-label={`Código da opção ${i + 1}`} value={o.value ?? ""} onChange={(e) => update(i, { value: e.target.value })} className="h-8 font-mono text-xs" placeholder={toSnake(o.label, "opcao")} />}
              {dups.has(i) && (
                <p role="alert" className="text-xs font-medium text-danger">
                  ⚠ Opção repetida
                </p>
              )}
            </div>
            <Button size="icon" variant="ghost" aria-label={`Subir opção ${i + 1}`} disabled={i === 0} onClick={() => move(i, -1)}>
              <ArrowUp className="h-4 w-4" aria-hidden />
            </Button>
            <Button size="icon" variant="ghost" aria-label={`Descer opção ${i + 1}`} disabled={i === options.length - 1} onClick={() => move(i, 1)}>
              <ArrowDown className="h-4 w-4" aria-hidden />
            </Button>
            <Button size="icon" variant="ghost" aria-label={`Remover opção ${i + 1}`} onClick={() => onChange(options.filter((_, k) => k !== i))}>
              <Trash2 className="h-4 w-4" aria-hidden />
            </Button>
          </li>
        ))}
      </ul>
      <Button
        size="sm"
        onClick={() => {
          onChange([...options, { label: "" }]);
          setTimeout(() => last.current?.focus(), 30);
        }}
      >
        <Plus className="h-4 w-4" aria-hidden /> Adicionar opção
      </Button>

      <div className="space-y-1.5">
        <label htmlFor={`${id}-bulk`} className="text-sm font-medium">
          Colar várias opções <span className="font-normal text-muted">(uma por linha)</span>
        </label>
        <Textarea id={`${id}-bulk`} rows={3} value={bulk} onChange={(e) => setBulk(e.target.value)} placeholder={"Consultoria\nSuporte técnico\nTreinamento"} className="min-h-16" />
        <Button size="sm" disabled={!bulk.trim()} onClick={addBulk}>
          <ClipboardPaste className="h-4 w-4" aria-hidden /> Adicionar linhas
        </Button>
        {note && (
          <p role="status" className="text-xs text-muted">
            {note}
          </p>
        )}
      </div>

      <Checkbox label="Mostrar códigos das opções (avançado, para planilhas importadas)" checked={showValues} onChange={(e) => setShowValues(e.target.checked)} />

      <div className="space-y-1.5">
        <label htmlFor={`${id}-def`} className="text-sm font-medium">
          Opção já selecionada ao abrir o formulário
        </label>
        <Select id={`${id}-def`} value={defaultValue} onChange={(e) => onDefaultChange(e.target.value)}>
          <option value="">Nenhum</option>
          {options.filter((o) => o.label.trim()).map((o, i) => (
            <option key={i} value={o.value?.trim() || toSnake(o.label, "opcao")}>
              {o.label}
            </option>
          ))}
        </Select>
      </div>
    </fieldset>
  );
}
