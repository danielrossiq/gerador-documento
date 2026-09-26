"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { duplicateIndexes, OptionsEditor, type Opt } from "@/components/editor/options-editor";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, Input, Select } from "@/components/ui/form";
import { api, errorMessage } from "@/lib/api";
import { FIELD_TYPE_LIST } from "@/lib/fields/meta";
import type { FieldType, KitFieldOut } from "@/lib/types";

const TYPES = FIELD_TYPE_LIST.map((t) => t.value) as [FieldType, ...FieldType[]];
const schema = z.object({
  label: z.string().trim().min(1, "Dê um nome ao campo.").max(200, "Use até 200 caracteres."),
  type: z.enum(TYPES),
  required: z.boolean(),
  mask: z.string().max(100, "Use até 100 caracteres."),
});
type Values = z.infer<typeof schema>;

/** Criar/editar um campo compartilhado do kit. O tipo é fixo depois de criado (o mapeamento com os
 * documentos depende dele — trocar o tipo quebraria os campos já mapeados). */
export function KitFieldDialog({ open, onOpenChange, kitId, field, onSaved }: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  kitId: string;
  field?: KitFieldOut | null;
  onSaved: () => void;
}) {
  const editing = !!field;
  const [options, setOptions] = useState<Opt[]>([]);
  const [defaultValue, setDefaultValue] = useState("");
  const [serverError, setServerError] = useState<string | null>(null);
  const { register, handleSubmit, reset, watch, formState } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { label: "", type: "text_short", required: false, mask: "" },
  });
  const type = watch("type");

  useEffect(() => {
    if (!open) return;
    reset({ label: field?.label ?? "", type: field?.type ?? "text_short", required: field?.required ?? false, mask: field?.mask ?? "" });
    setOptions((field?.options ?? []).map((o) => ({ label: o.label, value: o.value })));
    setDefaultValue(field?.default_value != null ? String(field.default_value) : "");
    setServerError(null);
  }, [open, field, reset]);

  const optionsDup = duplicateIndexes(options).size > 0;
  const emptyOptions = type === "select" && options.some((o) => !o.label.trim());

  async function submit(v: Values) {
    setServerError(null);
    try {
      if (editing && field) {
        await api.patch(`/kit-fields/${field.id}`, {
          label: v.label.trim(), required: v.required, mask: v.mask.trim() || null, default_value: defaultValue || null,
        });
        if (field.type === "select") {
          await api.put(`/kit-fields/${field.id}/options`, { options: options.map((o) => ({ label: o.label.trim(), value: o.value?.trim() || null })) });
        }
      } else {
        await api.post(`/kits/${kitId}/fields`, {
          label: v.label.trim(), type: v.type, required: v.required, mask: v.type === "text_short" ? v.mask.trim() || null : null,
          default_value: defaultValue || null, options: v.type === "select" ? options.map((o) => ({ label: o.label.trim(), value: o.value?.trim() || null })) : undefined,
        });
      }
      onSaved();
      onOpenChange(false);
    } catch (e) {
      setServerError(errorMessage(e));
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={editing ? "Editar dado em comum" : "Novo dado em comum"}
      description="Preenchido uma vez no formulário do kit; vale para todo documento mapeado a ele."
      footer={
        <>
          <Button onClick={() => onOpenChange(false)}>Cancelar</Button>
          <Button variant="primary" loading={formState.isSubmitting} onClick={handleSubmit(submit)} disabled={optionsDup || emptyOptions}>
            {editing ? "Salvar" : "Criar campo"}
          </Button>
        </>
      }
    >
      <form onSubmit={handleSubmit(submit)} noValidate className="space-y-4">
        {serverError && (
          <p role="alert" className="rounded-md border border-danger/30 bg-danger-soft p-2 text-sm text-danger">
            {serverError}
          </p>
        )}
        <Field label="Nome do campo" error={formState.errors.label?.message} required>
          {(a) => <Input autoFocus {...a} {...register("label")} />}
        </Field>
        <Field label="Tipo" help={editing ? "Não pode ser alterado depois de criado." : undefined}>
          {(a) => (
            <Select disabled={editing} {...a} {...register("type")}>
              {FIELD_TYPE_LIST.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </Select>
          )}
        </Field>
        {type === "select" && (
          <OptionsEditor options={options} onChange={setOptions} defaultValue={defaultValue} onDefaultChange={setDefaultValue} />
        )}
        <Checkbox label="Obrigatório" {...register("required")} />
        {type === "text_short" && (
          <Field label="Máscara" help="# = dígito, A = letra, * = qualquer. Ex.: ####-AA" error={formState.errors.mask?.message}>
            {(a) => <Input className="font-mono text-xs" {...a} {...register("mask")} />}
          </Field>
        )}
      </form>
    </Dialog>
  );
}
