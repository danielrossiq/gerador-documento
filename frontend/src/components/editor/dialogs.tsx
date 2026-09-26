"use client";

import { useQuery } from "@tanstack/react-query";
import { History, RotateCcw } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Alert, Badge, Spinner } from "@/components/ui/misc";
import { api, errorMessage } from "@/lib/api";
import type { FieldOut, VersionOut } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

export function DeleteFieldDialog({ field, open, onOpenChange, onConfirm }: {
  field: FieldOut | null;
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onConfirm: (mode: "keep_text" | "remove_text") => Promise<void>;
}) {
  const [mode, setMode] = useState<"keep_text" | "remove_text">("keep_text");
  const [busy, setBusy] = useState(false);
  if (!field) return null;
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={`Excluir o campo “${field.label}”?`}
      description={field.occurrences ? `Ele aparece ${field.occurrences} ${field.occurrences === 1 ? "vez" : "vezes"} no documento. O que fazer com esse trecho?` : "Este campo não aparece no documento."}
      size="sm"
      footer={
        <>
          <Button onClick={() => onOpenChange(false)}>Cancelar</Button>
          <Button
            variant="danger"
            loading={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onConfirm(mode);
              } finally {
                setBusy(false);
              }
            }}
          >
            Excluir campo
          </Button>
        </>
      }
    >
      {field.occurrences > 0 && (
        <fieldset className="space-y-2">
          <legend className="sr-only">Destino do texto</legend>
          {(
            [
              ["keep_text", "Manter o texto original no documento", "O trecho volta a ser texto comum (ex.: “João da Silva”)."],
              ["remove_text", "Remover o trecho do documento", "O texto deixa de existir no documento."],
            ] as const
          ).map(([v, t, d]) => (
            <label key={v} className="flex cursor-pointer items-start gap-2 rounded-md border border-border p-3 has-[:checked]:border-primary has-[:checked]:bg-primary-soft">
              <input type="radio" name="mode" className="mt-1 accent-[var(--primary)]" checked={mode === v} onChange={() => setMode(v)} />
              <span>
                <span className="block text-sm font-medium">{t}</span>
                <span className="block text-xs text-muted">{d}</span>
              </span>
            </label>
          ))}
        </fieldset>
      )}
    </Dialog>
  );
}

/** Histórico de versões (um envio de arquivo ou uma restauração cada). A mais recente já está em uso — sem
 * etapa de publicação: salvar no editor já vale para a próxima geração. */
export function VersionsDialog({ open, onOpenChange, generatorId, onRestored }: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  generatorId: string;
  onRestored: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["versions", generatorId], enabled: open, queryFn: () => api.get<{ items: (VersionOut & { source_filename?: string | null })[] }>(`/generators/${generatorId}/versions`) });

  async function restore(v: VersionOut) {
    setBusy(v.id);
    setError(null);
    try {
      await api.post(`/generators/${generatorId}/versions/${v.id}/restore`);
      setConfirming(null);
      await q.refetch();
      onRestored();
      onOpenChange(false);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { setConfirming(null); onOpenChange(o); }} title="Histórico de versões" description="Cada documento enviado (ou versão restaurada) fica guardado aqui. Restaurar cria uma nova versão — nada é apagado." size="lg">
      {error && <Alert tone="danger" className="mb-3">{error}</Alert>}
      {q.isLoading ? (
        <Spinner />
      ) : q.error ? (
        <Alert tone="danger" title="Não foi possível carregar as versões">{errorMessage(q.error)}</Alert>
      ) : (
        <ul className="divide-y divide-border rounded-md border border-border">
          {q.data?.items.map((v, i) => (
            <li key={v.id} className="flex flex-wrap items-center gap-3 p-3">
              <History className="h-4 w-4 text-muted" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">
                  Versão {v.version_number} {i === 0 && <Badge tone="success">Em uso</Badge>}
                </p>
                <p className="break-words text-xs text-muted">
                  {formatDateTime(v.created_at)} · {v.author ?? "—"} · {v.fields_count} campos{v.source_filename ? ` · ${v.source_filename}` : ""}{v.note ? ` · ${v.note}` : ""}
                </p>
              </div>
              {i !== 0 &&
                (confirming === v.id ? (
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="text-xs text-muted">Voltar para esta versão?</span>
                    <Button size="sm" onClick={() => setConfirming(null)}>Cancelar</Button>
                    <Button size="sm" variant="primary" loading={busy === v.id} onClick={() => restore(v)}>Restaurar</Button>
                  </span>
                ) : (
                  <Button size="sm" onClick={() => setConfirming(v.id)} aria-label={`Restaurar a versão ${v.version_number}`}>
                    <RotateCcw className="h-4 w-4" aria-hidden /> Restaurar…
                  </Button>
                ))}
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  );
}
