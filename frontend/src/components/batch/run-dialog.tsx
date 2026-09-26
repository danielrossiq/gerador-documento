"use client";

import { useEffect, useRef, useState } from "react";
import type { Row } from "@/components/batch/grid-state";
import { JobResult } from "@/components/jobs/job-result";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, Input } from "@/components/ui/form";
import { Alert } from "@/components/ui/misc";
import { api, ApiError, errorMessage } from "@/lib/api";
import type { JobOut } from "@/lib/types";
import { plural, uuid } from "@/lib/utils";

type Validation = { rows: { index: number; valid: boolean; errors: Record<string, string> }[]; valid_count: number; invalid_count: number };

/**
 * Confirmação e execução do lote. A validação do SERVIDOR é a autoridade: mesmo com o cliente dizendo "tudo certo",
 * validamos de novo. Se houver linhas inválidas, gerar só as válidas exige um aceite explícito.
 */
export function RunDialog({ open, onOpenChange, generator, names, rows, clientInvalid, pdfAvailable, onServerErrors, onFocusErrors }: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  generator: { id: string; name: string; filename_pattern: string };
  names: string[];
  rows: Row[]; // apenas linhas não vazias, na ordem enviada
  clientInvalid: number;
  pdfAvailable: boolean;
  onServerErrors: (m: Map<string, Record<string, string>>) => void;
  onFocusErrors: () => void;
}) {
  const [format, setFormat] = useState<"docx" | "pdf" | "both">("docx");
  const [pattern, setPattern] = useState(generator.filename_pattern);
  const [onlyValid, setOnlyValid] = useState(false);
  const [phase, setPhase] = useState<"config" | "sending" | "job">("config");
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [invalid, setInvalid] = useState(0);
  const idem = useRef(uuid());

  useEffect(() => {
    if (open) {
      idem.current = uuid(); // uma chave por confirmação: repetir o clique não duplica o lote
      setPhase("config");
      setJobId(null);
      setError(null);
      setOnlyValid(false);
      setInvalid(clientInvalid);
    }
  }, [open, clientInvalid]);

  async function start() {
    setError(null);
    setPhase("sending");
    try {
      const payload = rows.map((r) => Object.fromEntries(names.map((n) => [n, r.v[n] ?? ""])));
      const val = await api.post<Validation>(`/generators/${generator.id}/batch/validate`, { rows: payload });
      const map = new Map<string, Record<string, string>>();
      val.rows.forEach((r, i) => !r.valid && map.set(rows[i].id, r.errors));
      onServerErrors(map);
      setInvalid(val.invalid_count);
      if (val.invalid_count > 0 && !onlyValid) {
        setPhase("config");
        setError(`${plural(val.invalid_count, "linha tem", "linhas têm")} erro. Corrija-as ou confirme a geração somente das linhas válidas.`);
        return;
      }
      const job = await api.post<JobOut>(
        `/generators/${generator.id}/batches`,
        { rows: payload, format, only_valid: onlyValid, filename_pattern: pattern, idempotency_key: idem.current },
        { headers: { "Idempotency-Key": idem.current } },
      );
      setJobId(job.id);
      setPhase("job");
    } catch (e) {
      setPhase("config");
      setError(e instanceof ApiError && e.code === "PDF_CONVERTER_UNAVAILABLE" ? "A conversão para PDF não está disponível neste ambiente. Escolha DOCX." : errorMessage(e));
    }
  }

  const total = rows.length;
  const valid = total - invalid;
  const blocked = total === 0 || (invalid > 0 && !onlyValid) || (onlyValid && valid === 0);

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      dismissible={phase !== "sending"}
      title={phase === "job" ? "Gerando o lote" : "Gerar lote de documentos"}
      description={phase === "job" ? "Você pode fechar esta janela: o processamento continua e fica no Histórico." : `${generator.name} · ${plural(total, "documento", "documentos")}`}
      size="md"
      footer={
        phase === "job" ? undefined : (
          <>
            <Button onClick={() => onOpenChange(false)} disabled={phase === "sending"}>Cancelar</Button>
            <Button variant="primary" loading={phase === "sending"} disabled={blocked && !(invalid > 0)} onClick={start} data-testid="run-start">
              {invalid > 0 && !onlyValid ? "Validar" : `Gerar ${plural(onlyValid ? valid : total, "documento", "documentos")}`}
            </Button>
          </>
        )
      }
    >
      {phase === "job" && jobId ? (
        <JobResult jobId={jobId} onClose={() => onOpenChange(false)} />
      ) : (
        <div className="space-y-4">
          {error && <Alert tone="danger">{error}</Alert>}
          <fieldset>
            <legend className="mb-1.5 text-sm font-medium">Formato de saída</legend>
            <div className="flex flex-wrap gap-3">
              {(
                [["docx", "DOCX"], ["pdf", "PDF"], ["both", "DOCX e PDF"]] as const
              ).map(([v, t]) => (
                <label key={v} className="flex cursor-pointer items-center gap-2 text-sm">
                  <input type="radio" name="fmt" checked={format === v} onChange={() => setFormat(v)} disabled={v !== "docx" && !pdfAvailable} className="accent-[var(--primary)]" data-testid={`fmt-${v}`} />
                  {t}
                </label>
              ))}
            </div>
            {!pdfAvailable && <p className="mt-1 text-xs text-warning">PDF indisponível neste ambiente (LibreOffice não encontrado).</p>}
          </fieldset>

          <Field label="Nome dos arquivos" help="Ex.: Contrato_{nome_do_contratante}_{linha}. Nomes repetidos ganham _2, _3…">
            {(a) => <Input className="font-mono text-xs" value={pattern} onChange={(e) => setPattern(e.target.value)} {...a} />}
          </Field>

          {invalid > 0 && (
            <Alert tone="warning" title={`${plural(invalid, "linha com erro", "linhas com erro")}`}>
              <p>Corrija as células destacadas em vermelho — o painel de erros leva direto a cada uma.</p>
              <div className="mt-2">
                <Button size="sm" onClick={() => { onOpenChange(false); onFocusErrors(); }}>Ir para os erros</Button>
              </div>
              <div className="mt-3 border-t border-warning/30 pt-3">
                <Checkbox label={`Gerar somente as ${plural(valid, "linha válida", "linhas válidas")}. As ${invalid} inválidas ficarão de fora e aparecerão no relatório.`} checked={onlyValid} onChange={(e) => setOnlyValid(e.target.checked)} data-testid="only-valid" />
              </div>
            </Alert>
          )}
        </div>
      )}
    </Dialog>
  );
}
