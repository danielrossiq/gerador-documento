"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { GeneratorSteps } from "@/components/generators/steps";
import { AnalysisStep, checkDocx, DocxDropzone, UploadErrorAlert, type UploadError } from "@/components/generators/template-upload";
import { AppShell } from "@/components/layout/app-shell";
import { TrySampleButton } from "@/components/onboarding/samples";
import { Field, Input } from "@/components/ui/form";
import { Card } from "@/components/ui/misc";
import { api, ApiError, errorMessage } from "@/lib/api";
import type { GeneratorOut } from "@/lib/types";

/** "contrato_prestacao-servicos v2.docx" → "Contrato prestacao servicos v2" (dá para renomear depois). */
function nameFromFile(filename: string): string {
  const base = filename.replace(/\.docx$/i, "").replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
  return base ? base[0].toUpperCase() + base.slice(1) : "Novo gerador";
}

/** Etapa 1 de um gerador novo: nome (opcional) + envio do .docx. O gerador só é criado quando o arquivo chega. */
function NewGenerator() {
  const qc = useQueryClient();
  const router = useRouter();
  const params = useSearchParams();
  const legacyId = params.get("id"); // links antigos (?id=) para gerador sem .docx: a etapa Modelo desse gerador
  const [name, setName] = useState("");
  const [generatorId, setGeneratorId] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<UploadError | null>(null);

  useEffect(() => {
    if (legacyId) router.replace(`/generators/${legacyId}/template`);
  }, [legacyId, router]);

  async function send(f: File) {
    setError(null);
    const bad = checkDocx(f);
    if (bad) return setError(bad);
    setFile(f);
    setUploading(true);
    let gid: string | null = null;
    try {
      gid = (await api.post<GeneratorOut>("/generators", { name: name.trim() || nameFromFile(f.name) })).id;
      await api.upload(`/generators/${gid}/template`, f);
      qc.invalidateQueries({ queryKey: ["generators"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      setGeneratorId(gid);
    } catch (e) {
      // o gerador criado sem documento não fica "órfão" no painel: remove se o envio falhou
      if (gid) await api.delete(`/generators/${gid}`).catch(() => undefined);
      setError({ message: errorMessage(e), code: e instanceof ApiError ? e.code : undefined });
      setFile(null);
    } finally {
      setUploading(false);
    }
  }

  return (
    <AppShell>
      <div className="mb-6 space-y-4">
        <div>
          <Link href="/dashboard" className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg">
            <ArrowLeft className="h-4 w-4" aria-hidden /> Geradores
          </Link>
          <h1 className="mt-1 text-2xl font-bold tracking-tight">Novo gerador</h1>
          <p className="mt-1 text-sm text-muted">Comece pelo documento que você já usa. Depois você marca o que muda de um documento para outro.</p>
        </div>
        <div className="border-y border-border py-2">
          <GeneratorSteps id="novo" current="template" hasTemplate={false} fieldsCount={0} />
        </div>
      </div>

      <div className="mx-auto max-w-2xl">
        {error && <UploadErrorAlert error={error} />}
        {generatorId ? (
          <AnalysisStep generatorId={generatorId} />
        ) : (
          <Card className="space-y-5 p-6">
            <Field label="Nome do gerador" help="Opcional. Se deixar em branco, usamos o nome do arquivo — dá para mudar depois.">
              {(a) => <Input {...a} value={name} onChange={(e) => setName(e.target.value)} placeholder="Ex.: Contrato de prestação de serviços" maxLength={200} disabled={uploading} />}
            </Field>
            <DocxDropzone busy={uploading} file={file} onPick={send} />
            <ul className="grid gap-2 text-sm text-muted sm:grid-cols-3">
              <li className="flex gap-2"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />Formatação, tabelas, cabeçalho e rodapé preservados</li>
              <li className="flex gap-2"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />CPF, CNPJ, datas e valores sugeridos na hora</li>
              <li className="flex gap-2"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />Seu arquivo original não é alterado</li>
            </ul>
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
              <span className="text-sm text-muted">Não tem um documento à mão?</span>
              <TrySampleButton size="sm" />
            </div>
          </Card>
        )}
      </div>
    </AppShell>
  );
}

export default function NewGeneratorPage() {
  return (
    <Suspense>
      <NewGenerator />
    </Suspense>
  );
}
