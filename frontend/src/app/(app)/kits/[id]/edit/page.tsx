"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Layers, Pencil, Plus, Sparkles, Trash2 } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { AddDocumentDialog } from "@/components/kits/add-document-dialog";
import { KitFieldDialog } from "@/components/kits/kit-field-dialog";
import { MappingGrid } from "@/components/kits/mapping-grid";
import { AppShell } from "@/components/layout/app-shell";
import { KitNav } from "@/components/models/model-nav";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/form";
import { Alert, Badge, EmptyState, Skeleton } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { typeLabel } from "@/lib/fields/meta";
import type { KitFieldOut, KitFormPayload } from "@/lib/types";

export default function KitEditPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["kit-form", id], queryFn: () => api.get<KitFormPayload>(`/kits/${id}/form`) });
  const [addOpen, setAddOpen] = useState(false);
  const [fieldDialog, setFieldDialog] = useState<{ field: KitFieldOut | null } | null>(null);
  const [toDeleteItem, setToDeleteItem] = useState<{ id: string; name: string } | null>(null);
  const [toDeleteField, setToDeleteField] = useState<KitFieldOut | null>(null);
  const [autoBusy, setAutoBusy] = useState(false);

  const refresh = () => qc.invalidateQueries({ queryKey: ["kit-form", id] });

  async function saveName(v: string, currentName: string) {
    const trimmed = v.trim();
    if (!trimmed || trimmed === currentName) return;
    try {
      await api.patch(`/kits/${id}`, { name: trimmed });
      refresh();
    } catch (e) {
      toast.push({ tone: "danger", title: "Não foi possível renomear", description: errorMessage(e) });
    }
  }

  async function removeItem(itemId: string) {
    try {
      await api.delete(`/kits/${id}/items/${itemId}`);
      setToDeleteItem(null);
      refresh();
      toast.push({ tone: "success", title: "Documento removido do kit" });
    } catch (e) {
      toast.push({ tone: "danger", title: "Não foi possível remover", description: errorMessage(e) });
    }
  }

  async function deleteField(f: KitFieldOut) {
    try {
      await api.delete(`/kit-fields/${f.id}`);
      setToDeleteField(null);
      refresh();
      toast.push({ tone: "success", title: `Campo “${f.label}” excluído` });
    } catch (e) {
      toast.push({ tone: "danger", title: "Não foi possível excluir", description: errorMessage(e) });
    }
  }

  async function autoDetect() {
    setAutoBusy(true);
    try {
      const r = await api.post<{ created_fields: number; updated_fields: number }>(`/kits/${id}/auto-detect`);
      refresh();
      toast.push({
        tone: "success",
        title: r.created_fields ? `${r.created_fields} ${r.created_fields === 1 ? "dado em comum detectado" : "dados em comum detectados"}` : "Nada novo em comum encontrado",
        description: r.updated_fields ? `${r.updated_fields} campo(s) existente(s) foram atualizados.` : undefined,
      });
    } catch (e) {
      toast.push({ tone: "danger", title: "Não foi possível detectar", description: errorMessage(e) });
    } finally {
      setAutoBusy(false);
    }
  }

  if (q.isLoading) {
    return (
      <AppShell>
        <Skeleton className="mb-4 h-10 w-80" />
        <Skeleton className="h-96 w-full" />
      </AppShell>
    );
  }
  if (q.error) {
    const e = q.error as ApiError;
    return (
      <AppShell>
        <Alert tone="danger" title={e.code === "NOT_FOUND" ? "Kit não encontrado" : "Não foi possível abrir o kit"}>
          {errorMessage(e)}
        </Alert>
      </AppShell>
    );
  }
  const data = q.data!;
  const kit = data.kit;
  const usableCount = data.members.filter((m) => m.usable).length;

  return (
    <AppShell>
      <header className="mb-6 flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="icon" aria-label="Voltar aos kits" onClick={() => router.push("/kits")}>
          <ArrowLeft className="h-4 w-4" aria-hidden />
        </Button>
        <label htmlFor="kit-name" className="sr-only">Nome do kit</label>
        <Input
          id="kit-name"
          defaultValue={kit.name}
          onBlur={(e) => saveName(e.target.value, kit.name)}
          onKeyDown={(e) => e.key === "Enter" && (e.currentTarget as HTMLInputElement).blur()}
          className="h-9 max-w-md border-transparent bg-transparent text-lg font-semibold hover:border-border-strong"
        />
        <div className="ml-auto flex items-center gap-2">
          <KitNav id={id} current="edit" />
        </div>
      </header>

      {data.warnings.length > 0 && (
        <Alert tone="warning" className="mb-4" title="Atenção">
          {data.warnings.join(" ")}
        </Alert>
      )}

      <section aria-labelledby="docs-h" className="mb-8">
        <div className="mb-3 flex items-center justify-between">
          <h2 id="docs-h" className="text-lg font-semibold">Documentos do kit</h2>
          <Button onClick={() => setAddOpen(true)}>
            <Plus className="h-4 w-4" aria-hidden /> Adicionar documento
          </Button>
        </div>
        {data.members.length === 0 ? (
          <EmptyState
            icon={<Layers className="h-9 w-9" aria-hidden />}
            title="Nenhum documento ainda"
            description="Adicione dois ou mais modelos que usam os mesmos dados (nome, CPF, endereço…)."
            action={<Button variant="primary" onClick={() => setAddOpen(true)}><Plus className="h-4 w-4" aria-hidden /> Adicionar documento</Button>}
          />
        ) : (
          <ul className="divide-y divide-border rounded-md border border-border">
            {data.members.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center justify-between gap-2 p-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{m.generator_name}</p>
                  {m.usable ? (
                    <p className="text-xs text-muted">
                      {Object.keys(m.field_mapping).length} de {m.fields.length} campos vêm dos dados em comum
                    </p>
                  ) : (
                    <p className="text-xs text-danger">{m.reason}</p>
                  )}
                </div>
                <Button size="sm" variant="ghost" className="text-danger hover:bg-danger-soft" onClick={() => setToDeleteItem({ id: m.id, name: m.generator_name })}>
                  <Trash2 className="h-4 w-4" aria-hidden /> Remover
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="fields-h" className="mb-8">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 id="fields-h" className="text-lg font-semibold">Dados em comum</h2>
            <p className="text-sm text-muted">Preenchidos uma vez só no formulário do kit e usados em todos os documentos.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button onClick={autoDetect} loading={autoBusy} disabled={usableCount < 2} title={usableCount < 2 ? "Adicione ao menos 2 documentos com modelo enviado" : undefined}>
              <Sparkles className="h-4 w-4" aria-hidden /> Detectar automaticamente
            </Button>
            <Button variant="primary" onClick={() => setFieldDialog({ field: null })}>
              <Plus className="h-4 w-4" aria-hidden /> Novo dado em comum
            </Button>
          </div>
        </div>
        {data.fields.length === 0 ? (
          <EmptyState
            icon={<Sparkles className="h-9 w-9" aria-hidden />}
            title="Nenhum dado em comum ainda"
            description="Use “Detectar automaticamente” (com 2 documentos ou mais) ou crie um campo na mão."
          />
        ) : (
          <>
            <ul className="mb-4 divide-y divide-border rounded-md border border-border">
              {data.fields.map((f) => (
                <li key={f.id} className="flex flex-wrap items-center justify-between gap-2 p-3">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{f.label}</span>
                    <Badge>{typeLabel(f.type)}</Badge>
                    {f.required && <Badge tone="warning">obrigatório</Badge>}
                  </div>
                  <div className="flex gap-1">
                    <Button size="sm" onClick={() => setFieldDialog({ field: f })}>
                      <Pencil className="h-3.5 w-3.5" aria-hidden /> Editar
                    </Button>
                    <Button size="sm" variant="ghost" aria-label={`Excluir campo ${f.label}`} className="text-danger hover:bg-danger-soft" onClick={() => setToDeleteField(f)}>
                      <Trash2 className="h-3.5 w-3.5" aria-hidden />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
            {usableCount > 0 && (
              <>
                <h3 className="mb-2 text-sm font-semibold text-muted">De qual campo de cada documento vem cada dado</h3>
                <MappingGrid kitId={id} fields={data.fields} items={data.members} onChanged={refresh} />
              </>
            )}
          </>
        )}
      </section>

      <AddDocumentDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        excludeIds={new Set(data.members.map((m) => m.generator_id))}
        onAdded={async (generatorId) => {
          await api.post(`/kits/${id}/items`, { generator_id: generatorId });
          refresh();
          toast.push({ tone: "success", title: "Documento adicionado ao kit" });
        }}
      />
      <KitFieldDialog open={!!fieldDialog} onOpenChange={(o) => !o && setFieldDialog(null)} kitId={id} field={fieldDialog?.field ?? null} onSaved={refresh} />
      <ConfirmDialog
        open={!!toDeleteItem}
        onOpenChange={(o) => !o && setToDeleteItem(null)}
        title="Remover documento do kit?"
        description={toDeleteItem ? `“${toDeleteItem.name}” deixa de ser gerado junto com o kit. O modelo em si não é afetado.` : undefined}
        confirmLabel="Remover"
        danger
        onConfirm={() => toDeleteItem && removeItem(toDeleteItem.id)}
      />
      <ConfirmDialog
        open={!!toDeleteField}
        onOpenChange={(o) => !o && setToDeleteField(null)}
        title="Excluir dado em comum?"
        description={toDeleteField ? `“${toDeleteField.label}” deixa de existir; os documentos mapeados a ele passam a pedir o valor separadamente.` : undefined}
        confirmLabel="Excluir"
        danger
        onConfirm={() => toDeleteField && deleteField(toDeleteField)}
      />
    </AppShell>
  );
}
