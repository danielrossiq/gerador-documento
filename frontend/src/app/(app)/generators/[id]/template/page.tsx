"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, FileText, History, Info } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { VersionsDialog } from "@/components/editor/dialogs";
import { GeneratorHeader, stepHrefs } from "@/components/generators/steps";
import { AnalysisStep, checkUpload, DocxDropzone, UploadErrorAlert, usePdfImport, type UploadError } from "@/components/generators/template-upload";
import { AppShell } from "@/components/layout/app-shell";
import { Button, ButtonLink } from "@/components/ui/button";
import { Alert, Badge, Card, Skeleton } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import type { GeneratorOut, VersionOut } from "@/lib/types";
import { formatDateTime, plural } from "@/lib/utils";

type VersionRow = VersionOut & { source_filename?: string | null };

/**
 * Etapa 1 (Documento) de um modelo que já existe: envia o .docx/PDF que falta ou troca o atual.
 * Antes, um modelo sem documento levava a uma tela de erro ("Modelo não encontrado") sem caminho de volta.
 */
export default function TemplateStepPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<UploadError | null>(null);
  const allowPdf = usePdfImport();
  const [analysing, setAnalysing] = useState(false);
  const [versionsOpen, setVersionsOpen] = useState(false);

  const gen = useQuery({ queryKey: ["generator", id], queryFn: () => api.get<GeneratorOut>(`/generators/${id}`), retry: false });
  const versions = useQuery({
    queryKey: ["versions", id],
    enabled: !!gen.data?.has_template,
    queryFn: () => api.get<{ items: VersionRow[] }>(`/generators/${id}/versions`),
  });
  const g = gen.data;
  const current = versions.data?.items[0];

  async function send(f: File) {
    setError(null);
    const bad = checkUpload(f, allowPdf);
    if (bad) return setError(bad);
    const replacing = !!g?.has_template;
    setFile(f);
    setUploading(true);
    try {
      await api.upload(`/generators/${id}/template`, f);
      qc.invalidateQueries({ queryKey: ["generators"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["versions", id] });
      qc.invalidateQueries({ queryKey: ["generator", id] });
      if (replacing) {
        toast.push({ tone: "success", title: "Documento trocado", description: "Os campos foram mantidos e reposicionados pelo texto. Confira os que ficaram fora do documento." });
        router.push(`${stepHrefs(id).fields}`);
      } else {
        setAnalysing(true);
      }
    } catch (e) {
      setError({ message: errorMessage(e), code: e instanceof ApiError ? e.code : undefined });
      setFile(null);
    } finally {
      setUploading(false);
    }
  }

  if (gen.isLoading) {
    return (
      <AppShell>
        <Skeleton className="mb-4 h-24 w-full" />
        <Skeleton className="h-72 w-full" />
      </AppShell>
    );
  }
  if (gen.error || !g) {
    return (
      <AppShell>
        <Alert tone="danger" title="Modelo não encontrado">
          {errorMessage(gen.error)} <ButtonLink href="/models" size="sm" className="ml-2">Voltar aos modelos</ButtonLink>
        </Alert>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <GeneratorHeader
        id={id}
        name={g.name}
        step="template"
        hasTemplate={g.has_template}
        fieldsCount={g.fields_count}
        description={g.has_template ? "O documento Word que serve de base para este modelo." : "Falta enviar o documento Word que serve de base para este modelo."}
      >
        {g.has_template && (
          <ButtonLink href={stepHrefs(id).fields} variant="primary" size="sm">
            Próximo: Campos <ArrowRight className="h-4 w-4" aria-hidden />
          </ButtonLink>
        )}
      </GeneratorHeader>

      <div className="mx-auto max-w-2xl space-y-4">
        {error && <UploadErrorAlert error={error} />}
        {analysing ? (
          <AnalysisStep generatorId={id} />
        ) : g.has_template ? (
          <>
            <Card className="p-5">
              <h2 className="text-sm font-semibold text-muted">Documento em uso</h2>
              {versions.isLoading ? (
                <Skeleton className="mt-2 h-12" />
              ) : current ? (
                <div className="mt-2 flex flex-wrap items-center gap-3">
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-md bg-primary-soft text-primary" aria-hidden><FileText className="h-5 w-5" /></span>
                  <div className="min-w-0 flex-1">
                    <p className="break-words font-medium" data-testid="current-file">
                      {current.source_filename ?? "documento.docx"}
                      {current.source_format === "pdf" && <Badge tone="primary" className="ml-2 align-middle">convertido de PDF para Word</Badge>}
                    </p>
                    <p className="text-xs text-muted">Versão {current.version_number} · enviada em {formatDateTime(current.created_at)}{current.author ? ` por ${current.author}` : ""} · {plural(g.fields_count, "campo", "campos")}</p>
                  </div>
                  <Button size="sm" variant="ghost" onClick={() => setVersionsOpen(true)}>
                    <History className="h-4 w-4" aria-hidden /> Versões anteriores
                  </Button>
                </div>
              ) : (
                <p className="mt-2 text-sm text-muted">Não foi possível carregar os detalhes do arquivo.</p>
              )}
            </Card>

            <Card className="space-y-4 p-5">
              <div>
                <h2 className="text-base font-semibold">Trocar o documento</h2>
                <p className="mt-1 text-sm text-muted">Use quando o texto do contrato mudar. A versão atual fica guardada no histórico.</p>
              </div>
              <Alert tone="neutral" title="O que acontece com os campos">
                Os campos que você já criou continuam existindo e são reposicionados procurando o mesmo trecho no novo arquivo. Os que não forem encontrados ficam marcados como “fora do documento” na etapa Campos, para você decidir.
              </Alert>
              <DocxDropzone busy={uploading} file={file} onPick={send} title="Arraste o novo documento para cá" buttonLabel="Escolher novo arquivo" />
            </Card>
          </>
        ) : (
          <Card className="space-y-4 p-6">
            <Alert tone="warning" title="Este modelo ainda não tem documento">
              Envie o documento ({allowPdf ? "Word .docx ou PDF digitado" : "Word .docx"}) para marcar os campos e começar a gerar.
            </Alert>
            <DocxDropzone busy={uploading} file={file} onPick={send} />
          </Card>
        )}
        <p className="flex items-start gap-2 text-xs text-muted">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          Imagens, quebras de página, campos do Word e a estrutura das tabelas são preservados como estão; só o texto pode ser alterado no editor.
        </p>
      </div>
      <VersionsDialog open={versionsOpen} onOpenChange={setVersionsOpen} generatorId={id} onRestored={() => { gen.refetch(); versions.refetch(); toast.push({ tone: "success", title: "Versão restaurada" }); }} />
    </AppShell>
  );
}
