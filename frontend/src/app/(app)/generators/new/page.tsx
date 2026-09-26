"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FileText, Loader2, Sparkles, UploadCloud } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { AppShell, PageHeader } from "@/components/layout/app-shell";
import { TrySampleButton } from "@/components/onboarding/samples";
import { Button } from "@/components/ui/button";
import { Alert, Card } from "@/components/ui/misc";
import { api, ApiError, errorMessage } from "@/lib/api";
import type { GeneratorOut, SuggestionsPayload } from "@/lib/types";
import { cn, formatBytes } from "@/lib/utils";

const MAX_MB = 15;

const HINTS: Record<string, string> = {
  MACROS_NOT_ALLOWED: "Salve uma cópia sem macros (.docx, não .docm) e tente de novo.",
  NOT_A_DOCX: "Se o arquivo é um .doc antigo, abra no Word e use Salvar como → Documento do Word (.docx).",
  ENCRYPTED: "Remova a proteção por senha no Word antes de enviar.",
  DOCX_PARSE_FAILED: "Abra o arquivo no Word e salve-o novamente como .docx.",
};

/** "contrato_prestacao-servicos v2.docx" → "Contrato prestacao servicos v2" (dá pra renomear no editor). */
function nameFromFile(filename: string): string {
  const base = filename.replace(/\.docx$/i, "").replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
  return base ? base[0].toUpperCase() + base.slice(1) : "Novo modelo";
}

function NewModel() {
  const qc = useQueryClient();
  const params = useSearchParams();
  const existingId = params.get("id"); // modelo criado antes, ainda sem .docx ("Continuar configurando")
  const [generatorId, setGeneratorId] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<{ message: string; code?: string } | null>(null);
  const input = useRef<HTMLInputElement>(null);

  async function send(f: File) {
    setError(null);
    if (!f.name.toLowerCase().endsWith(".docx")) return setError({ message: "Envie um arquivo Word no formato .docx.", code: "NOT_A_DOCX" });
    if (f.size > MAX_MB * 1024 * 1024) return setError({ message: `O arquivo excede ${MAX_MB} MB.` });
    setFile(f);
    setUploading(true);
    let gid = existingId;
    try {
      if (!gid) gid = (await api.post<GeneratorOut>("/generators", { name: nameFromFile(f.name) })).id;
      await api.upload(`/generators/${gid}/template`, f);
      qc.invalidateQueries({ queryKey: ["generators"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      setGeneratorId(gid);
    } catch (e) {
      // o modelo criado sem documento não fica "órfão" no painel: remove se o envio falhou
      if (gid && !existingId) await api.delete(`/generators/${gid}`).catch(() => undefined);
      setError({ message: errorMessage(e), code: e instanceof ApiError ? e.code : undefined });
      setFile(null);
    } finally {
      setUploading(false);
    }
  }

  return (
    <AppShell>
      <PageHeader title="Novo modelo" description="Envie um documento que você já usa. Nós encontramos o que muda de um documento para outro." />
      <div className="mx-auto max-w-2xl">
        {error && (
          <Alert tone="danger" title={error.message} className="mb-4">
            {error.code && HINTS[error.code]}
          </Alert>
        )}

        {generatorId ? (
          <AnalysisStep generatorId={generatorId} />
        ) : (
          <Card className="p-6">
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDrag(true);
              }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDrag(false);
                const f = e.dataTransfer.files[0];
                if (f && !uploading) send(f);
              }}
              className={cn("flex flex-col items-center gap-3 rounded-lg border-2 border-dashed px-6 py-14 text-center transition-colors", drag ? "border-primary bg-primary-soft" : "border-border-strong bg-surface-2")}
            >
              {uploading ? (
                <>
                  <Loader2 className="h-10 w-10 animate-spin text-primary" aria-hidden />
                  <p className="font-medium" data-testid="picked-file">
                    Enviando {file?.name} <span className="font-normal text-muted">({file && formatBytes(file.size)})</span>
                  </p>
                </>
              ) : (
                <>
                  <UploadCloud className="h-10 w-10 text-primary" aria-hidden />
                  <p className="text-base font-semibold">Arraste seu documento .docx para cá</p>
                  <p className="text-sm text-muted">Contrato, recibo, declaração, procuração, proposta… até {MAX_MB} MB.</p>
                  <input
                    ref={input}
                    id="docx-file"
                    data-testid="docx-input"
                    type="file"
                    accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    className="sr-only"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      e.target.value = "";
                      if (f) send(f);
                    }}
                  />
                  <label htmlFor="docx-file" className="mt-1 inline-flex h-10 cursor-pointer items-center gap-2 rounded-md bg-primary px-5 text-sm font-medium text-primary-fg hover:bg-primary-hover focus-within:outline-2">
                    <FileText className="h-4 w-4" aria-hidden /> Escolher arquivo
                  </label>
                </>
              )}
            </div>
            <ul className="mt-5 grid gap-2 text-sm text-muted sm:grid-cols-3">
              <li className="flex gap-2"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />Formatação, tabelas, cabeçalho e rodapé preservados</li>
              <li className="flex gap-2"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />CPF, CNPJ, datas e valores sugeridos na hora</li>
              <li className="flex gap-2"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />Nada muda no seu arquivo original</li>
            </ul>
            {!existingId && (
              <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
                <span className="text-sm text-muted">Não tem um documento à mão?</span>
                <TrySampleButton size="sm" />
              </div>
            )}
          </Card>
        )}
      </div>
    </AppShell>
  );
}

const MESSAGES = ["Lendo o documento…", "Identificando tabelas, cabeçalho e rodapé…", "Procurando CPF, CNPJ, datas e valores…", "Sugerindo campos variáveis…"];

function AnalysisStep({ generatorId }: { generatorId: string }) {
  const router = useRouter();
  const [msg, setMsg] = useState(0);
  const [waited, setWaited] = useState(0);
  const gen = useQuery({
    queryKey: ["generator", generatorId, "analysis"],
    queryFn: () => api.get<GeneratorOut>(`/generators/${generatorId}`),
    refetchInterval: (q) => (q.state.data && ["done", "failed", "skipped"].includes(q.state.data.analysis_status ?? "") ? false : 1000),
  });
  const finished = ["done", "failed", "skipped"].includes(gen.data?.analysis_status ?? "");
  const suggestions = useQuery({
    queryKey: ["suggestions", generatorId, "wizard"],
    enabled: finished,
    queryFn: () => api.get<SuggestionsPayload>(`/generators/${generatorId}/suggestions`),
  });

  useEffect(() => {
    if (finished) return;
    const t = setInterval(() => {
      setMsg((m) => (m + 1) % MESSAGES.length);
      setWaited((w) => w + 1.8);
    }, 1800);
    return () => clearInterval(t);
  }, [finished]);

  const proceed = useCallback(() => router.replace(`/generators/${generatorId}/edit?panel=suggestions`), [router, generatorId]);
  useEffect(() => {
    if (waited > 90) proceed(); // análise lenta: segue para o editor (as sugestões chegam depois)
  }, [waited, proceed]);
  useEffect(() => {
    if (finished && suggestions.data) {
      const t = setTimeout(proceed, 1100);
      return () => clearTimeout(t);
    }
  }, [finished, suggestions.data, proceed]);

  const n = suggestions.data?.items.length ?? 0;
  return (
    <Card className="p-8 text-center" aria-live="polite">
      {!finished ? (
        <>
          <Loader2 className="mx-auto h-10 w-10 animate-spin text-primary" aria-hidden />
          <h2 className="mt-4 text-lg font-semibold">Analisando o documento</h2>
          <p className="mt-1 text-sm text-muted">{MESSAGES[msg]}</p>
          <div className="mt-6">
            <Button onClick={proceed}>Ir para o editor agora</Button>
          </div>
        </>
      ) : (
        <>
          {gen.data?.analysis_status === "failed" ? <Sparkles className="mx-auto h-10 w-10 text-warning" aria-hidden /> : <CheckCircle2 className="mx-auto h-10 w-10 text-success" aria-hidden />}
          <h2 className="mt-4 text-lg font-semibold">{gen.data?.analysis_status === "failed" ? "Análise indisponível" : "Documento pronto"}</h2>
          <p className="mt-1 text-sm text-muted">
            {gen.data?.analysis_status === "failed"
              ? "Não foi possível sugerir campos automaticamente. Selecione o texto no editor para criá-los."
              : n > 0
                ? `Encontramos ${n} ${n === 1 ? "trecho que parece variar" : "trechos que parecem variar"}. Revise e confirme.`
                : "Nenhuma sugestão automática. Selecione o texto no editor para criar campos."}
          </p>
          <div className="mt-6">
            <Button variant="primary" onClick={proceed}>Revisar no editor</Button>
          </div>
        </>
      )}
    </Card>
  );
}

export default function NewGeneratorPage() {
  return (
    <Suspense>
      <NewModel />
    </Suspense>
  );
}
