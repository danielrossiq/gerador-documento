"use client";

import { useQuery } from "@tanstack/react-query";
import { FileText } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Alert, Spinner } from "@/components/ui/misc";
import { api, errorMessage } from "@/lib/api";
import type { GeneratorOut, Paged } from "@/lib/types";

/** Escolhe, entre os modelos já existentes no workspace, qual entra no kit como um novo documento. */
export function AddDocumentDialog({ open, onOpenChange, excludeIds, onAdded }: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  excludeIds: Set<string>;
  onAdded: (generatorId: string) => Promise<void> | void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const q = useQuery({
    queryKey: ["generators", "for-kit"],
    enabled: open,
    queryFn: () => api.get<Paged<GeneratorOut>>("/generators?page_size=100&sort=name"),
  });

  const available = (q.data?.items ?? []).filter((g) => g.has_template && !excludeIds.has(g.id));

  async function add(g: GeneratorOut) {
    setBusy(g.id);
    setError(null);
    try {
      await onAdded(g.id);
      onOpenChange(false);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Adicionar documento ao kit"
      description="Só modelos que já têm um documento .docx enviado aparecem aqui."
      footer={<Button onClick={() => onOpenChange(false)}>Fechar</Button>}
    >
      {error && <Alert tone="danger" className="mb-3">{error}</Alert>}
      {q.isLoading ? (
        <Spinner />
      ) : available.length === 0 ? (
        <p className="text-sm text-muted">
          {q.data && q.data.items.length === 0
            ? "Você ainda não tem nenhum modelo pronto. Crie um em “Novo modelo” antes de montar o kit."
            : "Todos os seus modelos prontos já estão neste kit."}
        </p>
      ) : (
        <ul className="max-h-96 divide-y divide-border overflow-y-auto rounded-md border border-border">
          {available.map((g) => (
            <li key={g.id} className="flex items-center justify-between gap-3 p-3">
              <div className="flex min-w-0 items-center gap-2.5">
                <FileText className="h-4 w-4 shrink-0 text-muted" aria-hidden />
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{g.name}</p>
                  <p className="truncate text-xs text-muted">{g.fields_count} campos</p>
                </div>
              </div>
              <Button size="sm" variant="primary" loading={busy === g.id} onClick={() => add(g)}>
                Adicionar
              </Button>
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  );
}
