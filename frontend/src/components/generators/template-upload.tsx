"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, FileText, Loader2, Sparkles, UploadCloud } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { Alert, Card } from "@/components/ui/misc";
import { api } from "@/lib/api";
import type { GeneratorOut, SuggestionsPayload } from "@/lib/types";
import { cn, formatBytes } from "@/lib/utils";

export const MAX_MB = 15;

const HINTS: Record<string, string> = {
  MACROS_NOT_ALLOWED: "Salve uma cópia sem macros (.docx, não .docm) e tente de novo.",
  NOT_A_DOCX: "Se o arquivo é um .doc antigo, abra no Word e use Salvar como → Documento do Word (.docx).",
  ENCRYPTED: "Remova a proteção por senha no Word antes de enviar.",
  DOCX_PARSE_FAILED: "Abra o arquivo no Word e salve-o novamente como .docx.",
  EMPTY_DOCUMENT: "O arquivo não tem texto. Confira se enviou o documento certo.",
  FILE_TOO_LARGE: `Reduza imagens do documento ou envie um arquivo de até ${MAX_MB} MB.`,
};

export type UploadError = { message: string; code?: string };

/** Validação local antes de enviar (o servidor valida de novo, inclusive segurança do arquivo). */
export function checkDocx(f: File): UploadError | null {
  if (!f.name.toLowerCase().endsWith(".docx")) return { message: "Envie um arquivo Word no formato .docx.", code: "NOT_A_DOCX" };
  if (f.size > MAX_MB * 1024 * 1024) return { message: `O arquivo tem ${formatBytes(f.size)} e o limite é ${MAX_MB} MB.`, code: "FILE_TOO_LARGE" };
  return null;
}

export function UploadErrorAlert({ error, onRetry }: { error: UploadError; onRetry?: () => void }) {
  return (
    <Alert tone="danger" title={error.message} className="mb-4">
      {error.code && HINTS[error.code] && <p>{HINTS[error.code]}</p>}
      {onRetry && (
        <Button size="sm" className="mt-2" onClick={onRetry}>
          Tentar de novo
        </Button>
      )}
    </Alert>
  );
}

/** Área de envio do .docx: arrastar e soltar ou escolher (o botão é o próprio input, acessível por teclado). */
export function DocxDropzone({ busy, file, onPick, title = "Arraste seu documento .docx para cá", buttonLabel = "Escolher arquivo" }: {
  busy: boolean;
  file: File | null;
  onPick: (f: File) => void;
  title?: string;
  buttonLabel?: string;
}) {
  const id = useId();
  const [drag, setDrag] = useState(false);
  return (
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
        if (f && !busy) onPick(f);
      }}
      className={cn("flex flex-col items-center gap-3 rounded-lg border-2 border-dashed px-6 py-12 text-center transition-colors", drag ? "border-primary bg-primary-soft" : "border-border-strong bg-surface-2")}
    >
      {busy ? (
        <>
          <Loader2 className="h-10 w-10 animate-spin text-primary" aria-hidden />
          <p className="font-medium" role="status" data-testid="picked-file">
            Enviando {file?.name} <span className="font-normal text-muted">({file && formatBytes(file.size)})</span>
          </p>
        </>
      ) : (
        <>
          <UploadCloud className="h-10 w-10 text-primary" aria-hidden />
          <p className="text-base font-semibold">{title}</p>
          <p className="text-sm text-muted">Contrato, recibo, declaração, procuração, proposta… até {MAX_MB} MB.</p>
          <input
            id={id}
            data-testid="docx-input"
            type="file"
            accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            className="peer sr-only"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) onPick(f);
            }}
          />
          <label
            htmlFor={id}
            className="mt-1 inline-flex h-10 cursor-pointer items-center gap-2 rounded-md bg-primary px-5 text-sm font-medium text-primary-fg hover:bg-primary-hover peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-primary"
          >
            <FileText className="h-4 w-4" aria-hidden /> {buttonLabel}
          </label>
        </>
      )}
    </div>
  );
}

const MESSAGES = ["Lendo o documento…", "Identificando tabelas, cabeçalho e rodapé…", "Procurando CPF, CNPJ, datas e valores…", "Sugerindo campos…"];

/** Depois do envio: acompanha a análise (sugestões de campos) e leva à etapa Campos. */
export function AnalysisStep({ generatorId }: { generatorId: string }) {
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

  const n = suggestions.data?.items.length ?? 0;
  const proceed = useCallback(() => router.replace(`/generators/${generatorId}/edit${n > 0 ? "?panel=suggestions" : ""}`), [router, generatorId, n]);
  useEffect(() => {
    if (waited > 90) router.replace(`/generators/${generatorId}/edit?panel=suggestions`); // análise lenta: segue (as sugestões chegam depois)
  }, [waited, router, generatorId]);
  useEffect(() => {
    if (finished && suggestions.data) {
      const t = setTimeout(proceed, 1400);
      return () => clearTimeout(t);
    }
  }, [finished, suggestions.data, proceed]);

  const failed = gen.data?.analysis_status === "failed";
  return (
    <Card className="p-8 text-center" aria-live="polite">
      {!finished ? (
        <>
          <Loader2 className="mx-auto h-10 w-10 animate-spin text-primary" aria-hidden />
          <h2 className="mt-4 text-lg font-semibold">Documento recebido. Procurando o que muda…</h2>
          <p className="mt-1 text-sm text-muted">{MESSAGES[msg]}</p>
          <div className="mt-6">
            <Button onClick={() => router.replace(`/generators/${generatorId}/edit?panel=suggestions`)}>Pular e ir para os campos</Button>
          </div>
        </>
      ) : (
        <>
          {failed ? <Sparkles className="mx-auto h-10 w-10 text-warning" aria-hidden /> : <CheckCircle2 className="mx-auto h-10 w-10 text-success" aria-hidden />}
          <h2 className="mt-4 text-lg font-semibold">{failed ? "Documento pronto (sem sugestões automáticas)" : "Documento pronto"}</h2>
          <p className="mt-1 text-sm text-muted">
            {failed
              ? "Não foi possível sugerir campos agora. Você cria os campos selecionando o texto no documento."
              : n > 0
                ? `Encontramos ${n} ${n === 1 ? "trecho que parece mudar" : "trechos que parecem mudar"} de um documento para outro. Confira na próxima etapa.`
                : "Nenhuma sugestão automática. Você cria os campos selecionando o texto no documento."}
          </p>
          <div className="mt-6">
            <Button variant="primary" onClick={proceed}>Ir para a etapa Campos</Button>
          </div>
        </>
      )}
    </Card>
  );
}
