"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { AlertTriangle, ChevronLeft, ChevronRight, Link2, Trash2 } from "lucide-react";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { duplicateIndexes, OptionsEditor, type Opt } from "@/components/editor/options-editor";
import { Button } from "@/components/ui/button";
import { Checkbox, Field, Input, Select } from "@/components/ui/form";
import { Badge } from "@/components/ui/misc";
import { api, ApiError, errorMessage } from "@/lib/api";
import { sameLabelFields, type FieldIssue } from "@/lib/fields/issues";
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
  name: z.string().refine((v) => v === "" || (NAME_RE.test(v) && !RESERVED_NAMES.includes(v)), "Use letras minúsculas, números e _, começando por letra (hoje, linha e gerador são reservados)."),
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

export type SaveReport = { state: "saving" | "saved" | "error"; message?: string };

export type FieldFormProps = {
  mode: "create" | "edit";
  generatorId: string;
  field?: FieldOut;
  /** Todos os campos do modelo (para avisar nomes repetidos e oferecer "usar campo existente"). */
  siblings: FieldOut[];
  issues?: FieldIssue[];
  seed?: { label: string; type: FieldType; example: string; text?: string };
  occurrenceNav?: { count: number; onPrev: () => void; onNext: () => void };
  onCreated?: (f: FieldOut) => void;
  onUseExisting?: (f: FieldOut) => void;
  onChanged?: (f: FieldOut) => void;
  onDelete?: () => void;
  onCancel?: () => void;
  onSaveState?: (r: SaveReport) => void;
};

/** Painel de configuração de um campo. Em edição, salva sozinho (e salva o que estiver pendente ao sair). */
export function FieldForm({ mode, generatorId, field, siblings, issues = [], seed, occurrenceNav, onCreated, onUseExisting, onChanged, onDelete, onCancel, onSaveState }: FieldFormProps) {
  const uid = useId();
  const [options, setOptions] = useState<Opt[]>(() => (field?.options ?? []).map((o) => ({ label: o.label, value: o.value })));
  const [saving, setSaving] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [serverError, setServerError] = useState<string | null>(null);
  const [optionsError, setOptionsError] = useState<string | null>(null);
  const [reuseId, setReuseId] = useState("");
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: valuesFromField(field, seed), mode: "onChange" });
  const { register, watch, handleSubmit, formState, setError, setValue, getValues } = form;
  const type = watch("type");
  const label = watch("label");
  const values = watch();
  const lastSent = useRef<string>(mode === "edit" ? JSON.stringify(toPayload(valuesFromField(field), (field?.options ?? []).map((o) => ({ label: o.label, value: o.value })))) : "");
  const pending = useRef<(() => Promise<void>) | null>(null);
  const mounted = useRef(true);
  const optionsDup = duplicateIndexes(options).size > 0;
  const emptyOptions = type === "select" && options.some((o) => !o.label.trim());
  const twins = sameLabelFields(siblings, label ?? "", field?.id);

  function applyServerError(e: unknown) {
    if (e instanceof ApiError) {
      if (e.code === "DUPLICATE_FIELD_NAME" || e.code === "INVALID_FIELD_NAME" || e.code === "RESERVED_FIELD_NAME") setError("name", { message: e.message });
      else if (e.code === "INVALID_DEFAULT") setError("default_value", { message: e.message });
      else setServerError(e.message);
    } else setServerError(errorMessage(e));
  }

  // ---- edição: salvamento automático (700 ms depois da última alteração; ao desmontar, salva o que faltou)
  const payloadNow = useMemo(() => toPayload(values, options), [values, options]);
  useEffect(() => {
    if (mode !== "edit" || !field) return;
    const key = JSON.stringify(payloadNow);
    if (key === lastSent.current || !formState.isValid || optionsDup || emptyOptions) {
      pending.current = null;
      return;
    }
    const run = async () => {
      pending.current = null;
      setSaving("saving");
      onSaveState?.({ state: "saving" });
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
        onSaveState?.({ state: "saved" });
        onChanged?.(out);
      } catch (e) {
        // campo excluído enquanto havia algo pendente: não há o que salvar nem erro a mostrar
        if (!mounted.current && e instanceof ApiError && e.status === 404) return onSaveState?.({ state: "saved" });
        setSaving("error");
        onSaveState?.({ state: "error", message: `Não foi possível salvar o campo “${payloadNow.label}”: ${errorMessage(e)}` });
        applyServerError(e);
      }
    };
    pending.current = run;
    const t = setTimeout(run, 700);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [payloadNow, mode, field?.id, formState.isValid, optionsDup, emptyOptions]);

  useEffect(() => {
    mounted.current = true;
    const onUnload = (e: BeforeUnloadEvent) => {
      if (pending.current) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", onUnload);
    return () => {
      mounted.current = false;
      window.removeEventListener("beforeunload", onUnload);
      void pending.current?.(); // trocou de campo/tela antes do salvamento automático: salva agora
    };
  }, []);

  // ---- criação
  const create = useCallback(async (v: Values) => {
    setServerError(null);
    setOptionsError(null);
    if (v.type === "select") {
      if (options.filter((o) => o.label.trim()).length === 0) return setOptionsError("Adicione pelo menos uma opção à lista.");
      if (optionsDup || emptyOptions) return setOptionsError("Corrija as opções vazias ou repetidas.");
    }
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
  const others = siblings.filter((s) => s.id !== field?.id);

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

      {mode === "create" && seed?.text && onUseExisting && others.length > 0 && (
        <div className="space-y-2 rounded-md border border-border p-3">
          <label htmlFor={`${uid}-reuse`} className="block text-sm font-medium">
            É uma informação que já tem campo?
          </label>
          <p className="text-xs text-muted">Ex.: o mesmo nome aparece em outro parágrafo. Usar o mesmo campo faz os dois trechos receberem o mesmo valor.</p>
          <div className="flex gap-2">
            <Select id={`${uid}-reuse`} value={reuseId} onChange={(e) => setReuseId(e.target.value)} className="h-9" data-testid="reuse-select">
              <option value="">Escolha um campo…</option>
              {others.map((f) => (
                <option key={f.id} value={f.id}>{f.label}</option>
              ))}
            </Select>
            <Button size="sm" className="h-9" disabled={!reuseId} onClick={() => { const f = others.find((x) => x.id === reuseId); if (f) onUseExisting(f); }} data-testid="reuse-apply">
              <Link2 className="h-4 w-4" aria-hidden /> Usar
            </Button>
          </div>
          <p className="pt-1 text-center text-xs font-medium uppercase tracking-wide text-muted">ou crie um campo novo</p>
        </div>
      )}

      {mode === "edit" && issues.length > 0 && (
        <ul className="space-y-1.5" aria-label="Pendências deste campo">
          {issues.map((i) => (
            <li key={i.kind} className={`flex gap-2 rounded-md border p-2 text-xs ${i.severity === "error" ? "border-danger/30 bg-danger-soft text-danger" : "border-warning/30 bg-warning-soft text-warning"}`}>
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
              <span className="text-fg">{i.message}</span>
            </li>
          ))}
        </ul>
      )}

      {serverError && (
        <p role="alert" className="rounded-md border border-danger/30 bg-danger-soft p-2 text-sm text-danger">
          {serverError}
        </p>
      )}

      <div className="space-y-1.5">
        <Field label="Nome do campo" help="É a pergunta que aparece no formulário e o título da coluna na planilha." error={formState.errors.label?.message} required>
          {(a) => <Input autoFocus={mode === "create"} placeholder="Ex.: Nome do contratante" {...a} {...register("label")} data-testid="field-label" />}
        </Field>
        {twins.length > 0 && !formState.errors.label && (
          <div role="status" className="flex gap-2 rounded-md border border-warning/30 bg-warning-soft p-2 text-xs" data-testid="duplicate-label">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
            <div className="text-fg">
              {mode === "create" ? (
                <>
                  Já existe um campo chamado “{twins[0].label}”. Se é a mesma informação,{" "}
                  {onUseExisting ? (
                    <button type="button" className="font-medium text-primary underline" onClick={() => onUseExisting(twins[0])}>use o campo existente</button>
                  ) : (
                    "use o campo existente"
                  )}
                  ; se não, dê um nome diferente (ex.: “{twins[0].label} de início”).
                </>
              ) : (
                <>Outro campo também se chama “{twins[0].label}”. No formulário e na planilha os dois vão aparecer iguais — dê um nome diferente.</>
              )}
            </div>
          </div>
        )}
      </div>

      <Field label="Tipo" help={meta?.hint}>
        {(a) => (
          <Select {...a} {...register("type")} data-testid="field-type">
            {FIELD_TYPE_LIST.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </Select>
        )}
      </Field>

      {type === "select" && (
        <>
          <OptionsEditor
            options={options}
            onChange={(o) => {
              setOptions(o);
              setOptionsError(null);
            }}
            defaultValue={values.default_value}
            onDefaultChange={(v) => setValue("default_value", v, { shouldDirty: true, shouldValidate: true })}
          />
          {optionsError && <p role="alert" className="text-xs font-medium text-danger">⚠ {optionsError}</p>}
        </>
      )}

      <Checkbox label={<>Obrigatório <span className="text-muted">— não deixa gerar sem preencher</span></>} {...register("required")} />

      {type === "select" && formState.errors.default_value && <p role="alert" className="text-xs font-medium text-danger">⚠ {formState.errors.default_value.message}</p>}
      {type === "checkbox" && <Checkbox label="Marcada por padrão" {...register("default_checked")} />}

      <details className="rounded-md border border-border p-3" open={!!(formState.errors.name || formState.errors.default_value || formState.errors.example)}>
        <summary className="cursor-pointer select-none text-sm font-medium">Mais opções <span className="font-normal text-muted">(ajuda, exemplo, valor padrão…)</span></summary>
        <div className="mt-3 space-y-4">
          <Field label="Texto de ajuda" help="Aparece embaixo do campo no formulário." error={formState.errors.description?.message}>
            {(a) => <Input {...a} {...register("description")} />}
          </Field>
          <Field label="Exemplo" help="Aparece como dica dentro do campo e é usado na prévia com dados de exemplo." error={formState.errors.example?.message}>
            {(a) => <Input {...a} {...register("example")} />}
          </Field>
          {type !== "select" && type !== "checkbox" && (
            <Field label="Valor já preenchido" help={type === "date" ? "Use dd/mm/aaaa. Quem preenche pode mudar." : type === "yes_no" ? "Sim ou Não. Quem preenche pode mudar." : "Quem preenche pode mudar."} error={formState.errors.default_value?.message}>
              {(a) => <Input {...a} {...register("default_value")} />}
            </Field>
          )}
          <Checkbox label="Pedir também na planilha (geração de vários documentos)" {...register("include_in_batch")} />
          <Field label="Grupo no formulário" help="Campos com o mesmo grupo aparecem juntos, sob esse título." error={formState.errors.group_name?.message}>
            {(a) => <Input {...a} {...register("group_name")} placeholder="Ex.: Dados do contratante" />}
          </Field>
          {type === "text_short" && (
            <>
              <Field label="Formato obrigatório" help="# = número, A = letra, * = qualquer. Ex.: ####-AA" error={formState.errors.mask?.message}>
                {(a) => <Input className="font-mono text-xs" {...a} {...register("mask")} />}
              </Field>
              <Field label="Tamanho máximo (caracteres)" error={formState.errors.max_length?.message}>
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
            <Field label="Como a data sai no documento">
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
              <Field label="Texto se marcada" help="Padrão: ☒">{(a) => <Input {...a} {...register("checked_text")} />}</Field>
              <Field label="Texto se desmarcada" help="Padrão: ☐">{(a) => <Input {...a} {...register("unchecked_text")} />}</Field>
            </div>
          )}
          <Field label="Código do campo" help={mode === "create" ? `Usado em planilhas importadas e no nome do arquivo. Automático: ${previewName}` : "Usado em planilhas importadas e no nome do arquivo. Não pode repetir."} error={formState.errors.name?.message}>
            {(a) => <Input className="font-mono text-xs" placeholder={mode === "create" ? previewName : undefined} {...a} {...register("name")} />}
          </Field>
        </div>
      </details>

      {mode === "create" ? (
        <div className="flex flex-wrap justify-end gap-2 pt-2">
          <Button onClick={onCancel}>Cancelar</Button>
          <Button type="submit" variant="primary" loading={formState.isSubmitting} data-testid="create-field">
            Criar campo
          </Button>
        </div>
      ) : (
        <div className="space-y-3 border-t border-border pt-3">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
            <span aria-live="polite" data-testid="field-save-state">
              {saving === "saving" ? "Salvando…" : saving === "saved" ? "Alterações salvas." : saving === "error" ? <span className="text-danger">Não foi possível salvar.</span> : "As alterações são salvas sozinhas."}
            </span>
            {occurrenceNav && (
              <span className="flex items-center gap-1">
                <Badge tone={occurrenceNav.count ? "primary" : "warning"}>{occurrenceNav.count ? `${occurrenceNav.count}× no documento` : "Fora do documento"}</Badge>
                {occurrenceNav.count > 1 && (
                  <>
                    <Button size="icon" variant="ghost" aria-label="Ocorrência anterior no documento" onClick={occurrenceNav.onPrev}>
                      <ChevronLeft className="h-4 w-4" aria-hidden />
                    </Button>
                    <Button size="icon" variant="ghost" aria-label="Próxima ocorrência no documento" onClick={occurrenceNav.onNext}>
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
