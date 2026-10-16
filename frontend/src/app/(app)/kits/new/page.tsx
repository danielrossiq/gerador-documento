"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, FileText, Layers } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { AppShell, PageHeader } from "@/components/layout/app-shell";
import { TrySampleButton } from "@/components/onboarding/samples";
import { Button, ButtonLink } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { Alert, Card, Skeleton } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import type { GeneratorOut, KitOut, Paged } from "@/lib/types";
import { cn, plural } from "@/lib/utils";

/**
 * Um passo só: nome + quais modelos entram. Ao criar, os documentos são adicionados e os dados em comum
 * detectados na hora — antes eram 4 etapas separadas (criar, adicionar um a um, detectar, mapear).
 */
export default function NewKitPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const models = useQuery({
    queryKey: ["generators", "for-kit"],
    queryFn: () => api.get<Paged<GeneratorOut>>("/generators?page_size=100&sort=name"),
  });
  const ready = (models.data?.items ?? []).filter((g) => g.has_template);

  function toggle(id: string) {
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  }

  async function create() {
    setError(null);
    if (!name.trim()) return setError("Dê um nome ao kit.");
    if (picked.length < 2) return setError("Escolha pelo menos 2 modelos — o kit serve para preencher vários documentos de uma vez.");
    setBusy(true);
    let kit: KitOut | null = null;
    try {
      kit = await api.post<KitOut>("/kits", { name: name.trim(), description: null });
      for (const gid of picked) await api.post(`/kits/${kit.id}/items`, { generator_id: gid });
      const r = await api.post<{ created_fields: number }>(`/kits/${kit.id}/auto-detect`);
      qc.invalidateQueries();
      toast.push(
        r.created_fields
          ? { tone: "success", title: `Kit criado com ${plural(r.created_fields, "dado em comum", "dados em comum")}`, description: "Confira o que vai ser preenchido uma vez só." }
          : { tone: "info", title: "Kit criado", description: "Não achamos dados com o mesmo nome nos modelos — ligue-os manualmente na tabela." },
      );
      router.push(`/kits/${kit.id}/edit`);
    } catch (e) {
      setError(errorMessage(e));
      if (kit) router.push(`/kits/${kit.id}/edit`); // o kit já existe: segue para terminar a configuração lá
      setBusy(false);
    }
  }

  return (
    <AppShell>
      <PageHeader title="Novo kit" description="Junte modelos de documentos que sempre andam juntos e preencha os dados em comum (nome, CPF, endereço…) uma vez só." />
      <div className="mx-auto max-w-3xl space-y-4">
        {error && <Alert tone="danger" title={error} />}
        <Card className="space-y-6 p-6">
          <Field label="Nome do kit" required help="Ex.: Admissão de funcionário, Locação de imóvel">
            {(a) => <Input autoFocus {...a} value={name} onChange={(e) => setName(e.target.value)} />}
          </Field>

          <fieldset className="min-w-0">
            <legend className="mb-2 text-sm font-medium">
              Quais documentos fazem parte do kit? <span className="font-normal text-muted">({picked.length} {picked.length === 1 ? "escolhido" : "escolhidos"})</span>
            </legend>
            {models.isLoading ? (
              <div className="grid gap-2 sm:grid-cols-2"><Skeleton className="h-16" /><Skeleton className="h-16" /></div>
            ) : ready.length < 2 ? (
              <div className="rounded-md border border-dashed border-border-strong p-5 text-sm">
                <p className="font-medium">Você precisa de pelo menos 2 modelos prontos (com documento enviado) para montar um kit.</p>
                <p className="mt-1 text-muted">{ready.length === 1 ? "Você tem 1 até agora." : "Você ainda não tem nenhum."} Crie outro a partir de um documento que você já usa — ou veja como funciona com o exemplo.</p>
                <div className="mt-4 flex flex-wrap gap-2">
                  <ButtonLink href="/generators/new" variant="primary" size="sm">Novo modelo</ButtonLink>
                  <TrySampleButton kind="kit" size="sm" />
                </div>
              </div>
            ) : (
              <ul className="grid grid-cols-[minmax(0,1fr)] gap-2 sm:grid-cols-2">
                {ready.map((g) => {
                  const on = picked.includes(g.id);
                  return (
                    <li key={g.id}>
                      <label className={cn("flex cursor-pointer items-start gap-3 rounded-md border p-3 transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-primary", on ? "border-primary bg-primary-soft" : "border-border hover:bg-surface-2")}>
                        <input type="checkbox" className="sr-only" checked={on} onChange={() => toggle(g.id)} data-testid="kit-pick" aria-label={g.name} />
                        <span className={cn("mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded border", on ? "border-primary bg-primary text-primary-fg" : "border-border-strong bg-surface")} aria-hidden>
                          {on && <Check className="h-3.5 w-3.5" />}
                        </span>
                        <span className="min-w-0">
                          <span className="flex items-center gap-1.5 text-sm font-medium"><FileText className="h-4 w-4 shrink-0 text-muted" aria-hidden /><span className="truncate">{g.name}</span></span>
                          <span className="text-xs text-muted">{plural(g.fields_count, "campo", "campos")}</span>
                        </span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            )}
          </fieldset>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
            <p className="text-xs text-muted">Os campos com o mesmo nome nos modelos escolhidos viram um só no formulário do kit.</p>
            <Button variant="primary" loading={busy} disabled={ready.length < 2} onClick={create} data-testid="create-kit">
              <Layers className="h-4 w-4" aria-hidden /> Criar kit
            </Button>
          </div>
        </Card>
      </div>
    </AppShell>
  );
}
