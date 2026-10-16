"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ClipboardCheck, FileUp, MousePointerClick, Sparkles, Wand2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, ButtonLink, type ButtonProps } from "@/components/ui/button";
import { Card } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import type { GeneratorOut, KitOut } from "@/lib/types";

/** Cria um modelo (ou kit) de exemplo pronto e abre direto na tela de preencher — tempo até o 1º documento ≈ 1 min. */
export function TrySampleButton({ kind = "generator", children, ...rest }: { kind?: "generator" | "kit" } & ButtonProps) {
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    try {
      if (kind === "kit") {
        const k = await api.post<KitOut>("/samples/kit");
        qc.invalidateQueries();
        toast.push({ tone: "success", title: "Kit de exemplo criado", description: "Contrato e recibo com nome, CPF e valor em comum." });
        router.push(`/kits/${k.id}/use`);
      } else {
        const g = await api.post<GeneratorOut>("/samples/generator");
        qc.invalidateQueries();
        toast.push({ tone: "success", title: "Modelo de exemplo criado", description: "Use “Preencher com dados de exemplo” e baixe o contrato pronto." });
        router.push(`/generators/${g.id}/use`);
      }
    } catch (e) {
      toast.push({ tone: "danger", title: "Não foi possível criar o exemplo", description: errorMessage(e) });
      setBusy(false);
    }
  }

  return (
    <Button loading={busy} onClick={run} data-testid={kind === "kit" ? "try-sample-kit" : "try-sample"} {...rest}>
      {!busy && <Wand2 className="h-4 w-4" aria-hidden />}
      {children ?? (kind === "kit" ? "Ver um kit de exemplo" : "Experimentar com um exemplo")}
    </Button>
  );
}

// As mesmas etapas que a pessoa vai ver no topo de cada tela do modelo (Documento → Campos → Revisão → Gerar).
const STEPS = [
  { icon: FileUp, title: "Documento", text: "Envie um documento que você já usa: contrato, recibo, declaração… em Word (.docx)." },
  { icon: MousePointerClick, title: "Campos", text: "Selecione o que muda (nome, CPF, valor…) e transforme em campo. Sugerimos os mais comuns." },
  { icon: ClipboardCheck, title: "Revisão", text: "Veja o documento com dados de exemplo e confira o que falta ajustar." },
  { icon: Sparkles, title: "Gerar", text: "Preencha um formulário e baixe Word ou PDF — ou gere vários de uma vez com uma planilha." },
];

/** Primeiro acesso: o que é o produto em 4 etapas e dois jeitos de começar. */
export function HowItWorks({ actions = true }: { actions?: boolean }) {
  return (
    <Card className="overflow-hidden" data-testid="onboarding">
      <div className="bg-linear-to-br from-primary-soft via-surface to-surface px-6 py-8 sm:px-10">
        <h2 className="text-xl font-bold tracking-tight sm:text-2xl">Transforme um documento que você já usa em um modelo</h2>
        <p className="mt-1 max-w-2xl text-sm text-muted">Chega de copiar, colar e caçar nome e CPF no Word. Faça uma vez, gere quantas vezes quiser.</p>
        <ol className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((s, i) => (
            <li key={s.title} className="flex gap-3">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-primary text-sm font-bold text-primary-fg" aria-hidden>{i + 1}</span>
              <div>
                <p className="flex items-center gap-1.5 font-semibold"><s.icon className="h-4 w-4 text-primary" aria-hidden />{s.title}</p>
                <p className="mt-0.5 text-sm text-muted">{s.text}</p>
              </div>
            </li>
          ))}
        </ol>
        {actions && <div className="mt-8 flex flex-wrap items-center gap-3">
          <ButtonLink href="/generators/new" variant="primary" size="lg"><FileUp className="h-4 w-4" aria-hidden /> Criar meu primeiro modelo</ButtonLink>
          <TrySampleButton size="lg">Experimentar com um exemplo</TrySampleButton>
          <span className="text-xs text-muted">Sem documento à mão? O exemplo (um contrato) fica pronto em segundos.</span>
        </div>}
      </div>
    </Card>
  );
}
