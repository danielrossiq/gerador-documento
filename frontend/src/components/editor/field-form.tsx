"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { ChevronLeft, ChevronRight, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { duplicateIndexes, OptionsEditor, type Opt } from "@/components/editor/options-editor";
import { Button } from "@/components/ui/button";
import { Checkbox, Field, Input, Select } from "@/components/ui/form";
import { Badge } from "@/components/ui/misc";
import { api, ApiError, errorMessage } from "@/lib/api";
import { FIELD_TYPE_LIST, FIELD_TYPE_META } from "@/lib/fields/meta";
import { NAME_RE, RESERVED_NAMES, toSnake } from "@/lib/fields/naming";
import type { FieldOut, FieldType } from "@/lib/types";

const TYPES = FIELD_TYPE_LIST.map((t) => t.value) as [FieldType, ...FieldType[]];

const schema = z.object({
  label: z.string().trim().min(1, "Dê um nome ao campo.").max(200, "Use até 200 caracteres."),
  type: z.enum(TYPES),
  required: z.boolean(),
  description: z.string().max(500, "Use até 500 caracteres."),
  example: z.string().max(300, "Use até 300 caracteres."),
  default_value: z.string(),
  default_checked: z.boolean(),
  include_in_batch: z.boolean(),
  name: z.string().refine((v) => v === "" || (NAME_RE.test(v) && !RESERVED_NAMES.includes(v)), "Use letras minúsculas, números e _, começando por letra (não use hoje, linha ou gerador — são reservados)."),
  group_name: z.string().max(100),
  mask: z.string().max(100),
  decimals: z.string().refine((v) => v === "" || /^\d$/.test(v), "Use um número de 0 a 9."),
  min: z.string(),
  max: z.string(),
  date_format: z.enum(["short", "long"]),
  max_length: z.string().refine((v) => v === "" || /^\d+$/.test(v), "Use um número inteiro."),
  checked_text: z.string().max(20),
  unchecked_text: z.string().max(20),
});
type Values = z.infer<typeof schema>;

function valuesFromField(f?: FieldOut, seed?: { label: string; type: FieldType; example: string }): Values {
  const c = (f?.config ?? {}) as Record<string, unknown>;
  const s = (k: string) => (c[k] === undefined || c[k] === null ? "" : String(c[k]));
  return {
    label: f?.label ?? seed?.label ?? "",
    type: f?.type ?? seed?.type ?? "text_short",
    required: f?.required ?? false,
    description: f?.description ?? "",
    example: f?.example ?? seed?.example ?? "",
    default_value: f && f.type !== "checkbox" && f.default_value != null ? String(f.default_value) : "",
    default_checked: f?.type === "checkbox" && !!f.default_value,
    include_in_batch: f?.include_in_batch ?? true,
    name: f?.name ?? "",
    group_name: f?.group_name ?? "",
    mask: f?.mask ?? "",
    decimals: s("decimals"), min: s("min"), max: s("max"),
    date_format: c.date_format === "long" ? "long" : "short",
    max_length: s("max_length"), checked_text: s("checked_text"), unchecked_text: s("unchecked_text"),
  };
}

function toPayload(v: Values, options: Opt[]) {
  const config: Record<string, unknown> = {};
  if (v.type === "number" && v.decimals !== "") config.decimals = Number(v.decimals);
  if ((v.type === "number" || v.type === "currency") && v.min.trim()) config.min = v.min.trim();
  if ((v.type === "number" || v.type === "currency") && v.max.trim()) config.max = v.max.trim();
  if (v.type === "date" && v.date_format === "long") config.date_format = "long";
  if (v.type === "text_short" && v.max_length) config.max_length = Number(v.max_length);
  if (v.type === "checkbox") {
    if (v.checked_text) config.checked_text = v.checked_text;
    if (v.unchecked_text) config.unchecked_text = v.unchecked_text;
  }
  return {
    label: v.label.trim(), type: v.type, required: v.required, description: v.description.trim() || null, example: v.example.trim() || null,
    default_value: v.type === "checkbox" ? (v.default_checked ? "Sim" : null) : v.default_value.trim() || null,
    include_in_batch: v.include_in_batch, group_name: v.group_name.trim() || null, mask: v.type === "text_short" ? v.mask.trim() || null : null,
    config, options: v.type === "select" ? options.map((o) => ({ label: o.label.trim(), value: o.value?.trim() || null })) : undefined,
  };
}

export type FieldFormProps = {
  mode: "create" | "edit";
  generatorId: string;
  field?: FieldOut;
  seed?: { label: string; type: FieldType; example: string; text?: string };
  occurrenceNav?: { count: number; onPrev: () => void; onNext: () => void };
  onCreated?: (f: FieldOut) => void;
  onChanged?: (f: FieldOut) => void;
  onDelete?: () => void;
  onCancel?: () => void;
  onBusy?: (busy: boolean) => void;
};

/** Painel de configuração de um campo. Em edição, salva sozinho (debounce) — sem botão "Salvar" para esquecer. */
export function FieldForm({ mode, generatorId, field, seed, occurrenceNav, onCreated, onChanged, onDelete, onCancel, onBusy }: FieldFormProps) {
  const [options, setOptions] = useState<Opt[]>(() => (field?.options ?? []).map((o) => ({ label: o.label, value: o.value })));
  const [saving, setSaving] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [serverError, setServerError] = useState<string | null>(null);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: valuesFromField(field, seed), mode: "onChange" });
  const { register, watch, handleSubmit, formState, setError, setValue, getValues } = form;
  const type = watch("type");
  const label = watch("label");
  const values = watch();
  const lastSent = useRef<string>(mode === "edit" ? JSON.stringify(toPayload(valuesFromField(field), (field?.options ?? []).map((o) => ({ label: o.label, value: o.value })))) : "");
  const optionsDup = duplicateIndexes(options).size > 0;
  const emptyOptions = type === "select" && options.some((o) => !o.label.trim());

  function applyServerError(e: unknown) {
    if (e instanceof ApiError) {
      if (e.code === "DUPLICATE_FIELD_NAME" || e.code === "INVALID_FIELD_NAME" || e.code === "RESERVED_FIELD_NAME") setError("name", { message: e.message });
      else if (e.code === "INVALID_DEFAULT") setError("default_value", { message: e.message });
      else setServerError(e.message);
    } else setServerError(errorMessage(e));
  }

  // ---- edição: salvamento automático
  const payloadNow = useMemo(() => toPayload(values, options), [values, options]);
  useEffect(() => {
    if (mode !== "edit" || !field) return;
    const key = JSON.stringify(payloadNow);
    if (key === lastSent.current || !formState.isValid || optionsDup || emptyOptions) return;
    const t = setTimeout(async () => {
      setSaving("saving");
      onBusy?.(true);
      try {
        const { options: opts, ...patch } = payloadNow;
        const cur = getValues();
        const body: Record<string, unknown> = { ...patch };
        if (cur.name && cur.name !== field.name) body.name = cur.name;
        let out = await api.patch<FieldOut>(`/fields/${field.id}`, body);
        if (cur.type === "select" && opts) {
          const r = await api.put<{ options: { id: string; label: string; value: string }[] }>(`/fields/${field.id}/options`, { options: opts });
          out = { ...out, options: r.options };
        }
        lastSent.current = key;
        setServerError(null);
        setSaving("saved");
        onChanged?.(out);
      } catch (e) {
        setSaving("error");
        applyServerError(e);
      } finally {
        onBusy?.(false);
      }
    }, 700);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [payloadNow, mode, field?.id, formState.isValid, optionsDup, emptyOptions]);

  // ---- criação
  const create = useCallback(async (v: Values) => {
    setServerError(null);
    if (v.type === "select" && (optionsDup || emptyOptions)) return setServerError("Corrija as opções da lista (vazias ou repetidas).");
    try {
      const body = { ...toPayload(v, options), name: v.name || null };
      const f = await api.post<FieldOut>(`/generators/${generatorId}/fields`, body);
      onCreated?.(f);
    } catch (e) {
      applyServerError(e);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [generatorId, options, optionsDup, emptyOptions, onCreated]);

  const meta = FIELD_TYPE_META[type];
  const previewName = toSnake(label || "campo");

  return (
    <form onSubmit={handleSubmit(create)} noValidate className="space-y-4" aria-label={mode === "create" ? "Novo campo" : `Configuração do campo ${field?.label}`}>
      {mode === "create" && seed?.text && (
        <div className="rounded-md border border-primary/30 bg-primary-soft p-3 text-sm">
          <p className="text-xs font-medium uppercase tracking-wide text-primary">Trecho selecionado</p>
          <p className="mt-1 break-words font-medium" data-testid="selected-text">
            “{seed.text}”
          </p>
        </div>
      )}
      {serverError && (
        <p role="alert" className="rounded-md border border-danger/30 bg-danger-soft p-2 text-sm text-danger">
          {serverError}
        </p>
      )}

      <Field label="Nome do campo" help="É assim que o campo aparece no formulário e na planilha." error={formState.errors.label?.message} required>
        {(a) => <Input autoFocus={mode === "create"} placeholder="Ex.: Nome do contratante" {...a} {...register("label")} />}
      </Field>

      <Field label="Tipo" help={meta?.hint}>
        {(a) => (
          <Select {...a} {...register("type")}>
            {FIELD_TYPE_LIST.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </Select>
        )}
      </Field>

      {type === "select" && (
        <OptionsEditor
          options={options}
          onChange={setOptions}
          defaultValue={values.default_value}
          onDefaultChange={(v) => setValue("default_value", v, { shouldDirty: true, shouldValidate: true })}
        />
      )}

      <div className="grid gap-2">
        <Checkbox label="Obrigatório" {...register("required")} />
        <Checkbox label="Incluir na planilha de lote" {...register("include_in_batch")} />
      </div>

      <Field label="Descrição / ajuda" help="Aparece abaixo do campo no formulário." error={formState.errors.description?.message}>
        {(a) => <Input {...a} {...register("description")} />}
      </Field>

      {type !== "select" && type !== "checkbox" && (
        <Field label="Valor padrão" help={type === "date" ? "dd/mm/aaaa" : type === "yes_no" ? "Sim ou Não" : undefined} error={formState.errors.default_value?.message}>
          {(a) => <Input {...a} {...register("default_value")} />}
        </Field>
      )}
      {type === "select" && formState.errors.default_value && <p role="alert" className="text-xs font-medium text-danger">⚠ {formState.errors.default_value.message}</p>}
      {type === "checkbox" && <Checkbox label="Marcado por padrão" {...register("default_checked")} />}

      <Field label="Texto de exemplo" help="Aparece como dica dentro do campo." error={formState.errors.example?.message}>
        {(a) => <Input {...a} {...register("example")} />}
      </Field>

      <details className="rounded-md border border-border p-3">
        <summary className="cursor-pointer select-none text-sm font-medium">Configurações avançadas</summary>
        <div className="mt-3 space-y-4">
          <Field label="Nome técnico" help={mode === "create" ? `Gerado automaticamente: ${previewName}` : "Usado nas planilhas e no nome do arquivo. Não pode repetir."} error={formState.errors.name?.message}>
            {(a) => <Input className="font-mono text-xs" placeholder={mode === "create" ? previewName : undefined} {...a} {...register("name")} />}
          </Field>
          <Field label="Grupo no formulário" help="Campos com o mesmo grupo ficam juntos." error={formState.errors.group_name?.message}>
            {(a) => <Input {...a} {...register("group_name")} />}
          </Field>
          {type === "text_short" && (
            <>
              <Field label="Máscara" help="# = dígito, A = letra, * = qualquer. Ex.: ####-AA" error={formState.errors.mask?.message}>
                {(a) => <Input className="font-mono text-xs" {...a} {...register("mask")} />}
              </Field>
              <Field label="Tamanho máximo" error={formState.errors.max_length?.message}>
                {(a) => <Input inputMode="numeric" {...a} {...register("max_length")} />}
              </Field>
            </>
          )}
          {(type === "number" || type === "currency") && (
            <div className="grid grid-cols-2 gap-3">
              {type === "number" && (
                <Field label="Casas decimais" error={formState.errors.decimals?.message} className="col-span-2">
                  {(a) => <Input inputMode="numeric" {...a} {...register("decimals")} />}
                </Field>
              )}
              <Field label="Mínimo">{(a) => <Input inputMode="decimal" {...a} {...register("min")} />}</Field>
              <Field label="Máximo">{(a) => <Input inputMode="decimal" {...a} {...register("max")} />}</Field>
            </div>
          )}
          {type === "date" && (
            <Field label="Formato no documento">
              {(a) => (
                <Select {...a} {...register("date_format")}>
                  <option value="short">21/09/2026</option>
                  <option value="long">21 de setembro de 2026</option>
                </Select>
              )}
            </Field>
          )}
          {type === "checkbox" && (
            <div className="grid grid-cols-2 gap-3">
              <Field label="Texto se marcado" help="Padrão: ☒">{(a) => <Input {...a} {...register("checked_text")} />}</Field>
              <Field label="Texto se desmarcado" help="Padrão: ☐">{(a) => <Input {...a} {...register("unchecked_text")} />}</Field>
            </div>
          )}
        </div>
      </details>

      {mode === "create" ? (
        <div className="flex flex-wrap justify-end gap-2 pt-2">
          <Button onClick={onCancel}>Cancelar</Button>
          <Button type="submit" variant="primary" loading={formState.isSubmitting} disabled={!formState.isValid}>
            Criar campo
          </Button>
        </div>
      ) : (
        <div className="space-y-3 border-t border-border pt-3">
          <div className="flex items-center justify-between gap-2 text-xs text-muted" aria-live="polite">
            <span>{saving === "saving" ? "Salvando alterações…" : saving === "saved" ? "Alterações salvas automaticamente." : saving === "error" ? "Não foi possível salvar." : "As alterações são salvas automaticamente."}</span>
            {occurrenceNav && (
              <span className="flex items-center gap-1">
                <Badge tone={occurrenceNav.count ? "primary" : "warning"}>{occurrenceNav.count ? `${occurrenceNav.count}× no documento` : "Não está no documento"}</Badge>
                {occurrenceNav.count > 1 && (
                  <>
                    <Button size="icon" variant="ghost" aria-label="Ocorrência anterior" onClick={occurrenceNav.onPrev}>
                      <ChevronLeft className="h-4 w-4" aria-hidden />
                    </Button>
                    <Button size="icon" variant="ghost" aria-label="Próxima ocorrência" onClick={occurrenceNav.onNext}>
                      <ChevronRight className="h-4 w-4" aria-hidden />
                    </Button>
                  </>
                )}
              </span>
            )}
          </div>
          <Button variant="ghost" className="text-danger hover:bg-danger-soft" onClick={onDelete}>
            <Trash2 className="h-4 w-4" aria-hidden /> Excluir campo…
          </Button>
        </div>
      )}
    </form>
  );
}
