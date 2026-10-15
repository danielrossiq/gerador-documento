"use client";

import { ArrowLeft, CheckCircle2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { GeneratorSteps } from "@/components/generators/steps";
import { AnalysisStep, DocxDropzone, UploadErrorAlert, useNewModelUpload } from "@/components/generators/template-upload";
import { AppShell } from "@/components/layout/app-shell";
import { TrySampleButton } from "@/components/onboarding/samples";
import { Field, Input } from "@/components/ui/form";
import { Card } from "@/components/ui/misc";

/** Etapa 1 de um modelo novo: nome (opcional) + envio do documento (.docx ou PDF digitado). */
function NewModel() {
  const router = useRouter();
  const params = useSearchParams();
  const legacyId = params.get("id"); // links antigos (?id=) para modelo sem documento: a etapa Documento desse modelo
  const [name, setName] = useState("");
  const upload = useNewModelUpload();

  useEffect(() => {
    if (legacyId) router.replace(`/generators/${legacyId}/template`);
  }, [legacyId, router]);

  return (
    <AppShell>
      <div className="mb-6 space-y-4">
        <div>
          <Link href="/models" className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg">
            <ArrowLeft className="h-4 w-4" aria-hidden /> Modelos
          </Link>
          <h1 className="mt-1 text-2xl font-bold tracking-tight">Novo modelo</h1>
          <p className="mt-1 text-sm text-muted">Comece pelo documento que você já usa. Depois você marca o que muda de um documento para outro.</p>
        </div>
        <div className="border-y border-border py-2">
          <GeneratorSteps id="novo" current="template" hasTemplate={false} fieldsCount={0} />
        </div>
      </div>

      <div className="mx-auto max-w-2xl">
        {upload.error && <UploadErrorAlert error={upload.error} />}
        {upload.generatorId ? (
          <AnalysisStep generatorId={upload.generatorId} />
        ) : (
          <Card className="space-y-5 p-6">
            <Field label="Nome do modelo" help="Opcional. Se deixar em branco, usamos o nome do arquivo — dá para mudar depois.">
              {(a) => <Input {...a} value={name} onChange={(e) => setName(e.target.value)} placeholder="Ex.: Contrato de prestação de serviços" maxLength={200} disabled={upload.uploading} />}
            </Field>
            <DocxDropzone busy={upload.uploading} file={upload.file} onPick={(f) => upload.send(f, name)} />
            <ul className="grid gap-2 text-sm text-muted sm:grid-cols-3">
              <li className="flex gap-2"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />Formatação, tabelas, cabeçalho e rodapé preservados</li>
              <li className="flex gap-2"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />CPF, CNPJ, datas e valores sugeridos na hora</li>
              <li className="flex gap-2"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />PDF digitado vira Word editável; escaneado não é aceito</li>
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

export default function NewModelPage() {
  return (
    <Suspense>
      <NewModel />
    </Suspense>
  );
}
