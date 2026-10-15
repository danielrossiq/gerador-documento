"use client";

import { useQueryClient } from "@tanstack/react-query";
import { FileSpreadsheet, UploadCloud } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Select } from "@/components/ui/form";
import { Alert, Badge } from "@/components/ui/misc";
import { api, errorMessage } from "@/lib/api";
import { formatBytes } from "@/lib/utils";

type PreviewField = {
  id: string;
  name: string;
  label: string;
  type: string;
  required: boolean;
  options: { label: string; value: string }[] | null;
};

type Preview = {
  import_id: string;
  filename: string;
  columns: string[];
  sample: string[][];
  row_count: number;
  suggested_mapping: (string | null)[];
  fields: PreviewField[];
};

type ApplyResponse = { rows: Record<string, string>[]; validation: ValidationOut };
type ValidationOut = {
  rows: { index: number; valid: boolean; errors: Record<string, string> }[];
  valid_count: number;
  invalid_count: number;
};

const UNKNOWN_OPTION_ERROR = "Opção inválida. Escolha uma das opções da lista.";

/** Um campo "lista suspensa" mapeado e os valores da planilha que não batem com nenhuma opção atual dele. */
type UnknownGroup = { field: PreviewField; newValues: string[]; selected: Set<string> };

function collectUnknownSelectValues(
  fields: PreviewField[],
  rows: Record<string, string>[],
  validation: ValidationOut,
): UnknownGroup[] {
  const groups: UnknownGroup[] = [];
  for (const f of fields) {
    if (f.type !== "select") continue;
    const known = new Set((f.options ?? []).flatMap((o) => [o.label.toLowerCase(), o.value.toLowerCase()]));
    const seen = new Set<string>();
    validation.rows.forEach((r, i) => {
      if (!r.errors[f.name] || r.errors[f.name] !== UNKNOWN_OPTION_ERROR) return;
      const raw = (rows[i]?.[f.name] ?? "").trim();
      if (raw && !known.has(raw.toLowerCase())) seen.add(raw);
    });
    if (seen.size > 0) groups.push({ field: f, newValues: [...seen], selected: new Set(seen) });
  }
  return groups;
}

export type ImportResult = { rows: Record<string, string>[]; mode: "replace" | "append"; invalid: number };

/** Importação em 2 etapas: envio (.xlsx/.csv) → mapeamento entre as colunas do arquivo e os campos do modelo. */
export function ImportDialog({ open, onOpenChange, generatorId, hasData, onImported }: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  generatorId: string;
  hasData: boolean;
  onImported: (r: ImportResult) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [mapping, setMapping] = useState<(string | null)[]>([]);
  const [mode, setMode] = useState<"replace" | "append">("replace");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unknowns, setUnknowns] = useState<UnknownGroup[] | null>(null);
  const [pending, setPending] = useState<ApplyResponse | null>(null);
  const qc = useQueryClient();

  useEffect(() => {
    if (open) {
      setFile(null);
      setPreview(null);
      setError(null);
      setUnknowns(null);
      setPending(null);
      setMode(hasData ? "append" : "replace");
    }
  }, [open, hasData]);

  async function upload(f: File) {
    setFile(f);
    setBusy(true);
    setError(null);
    try {
      const p = await api.upload<Preview>(`/generators/${generatorId}/batch/imports`, f);
      setPreview(p);
      setMapping(p.suggested_mapping);
    } catch (e) {
      setError(errorMessage(e));
      setFile(null);
    } finally {
      setBusy(false);
    }
  }

  async function apply() {
    if (!preview) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<ApplyResponse>(
        `/generators/${generatorId}/batch/imports/${preview.import_id}/apply`,
        { mapping },
      );
      const found = collectUnknownSelectValues(preview.fields, r.rows, r.validation);
      if (found.length > 0) {
        setPending(r);
        setUnknowns(found);
      } else {
        onImported({ rows: r.rows, mode, invalid: r.validation.invalid_count });
        onOpenChange(false);
      }
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  function toggleUnknownValue(fieldName: string, value: string) {
    setUnknowns((prev) =>
      (prev ?? []).map((g) => {
        if (g.field.name !== fieldName) return g;
        const selected = new Set(g.selected);
        if (selected.has(value)) selected.delete(value);
        else selected.add(value);
        return { ...g, selected };
      }),
    );
  }

  async function resolveUnknowns(addSelected: boolean) {
    if (!pending || !unknowns) return;
    setBusy(true);
    setError(null);
    try {
      if (addSelected) {
        for (const g of unknowns) {
          const toAdd = g.newValues.filter((v) => g.selected.has(v));
          if (toAdd.length === 0) continue;
          const options = [...(g.field.options ?? []), ...toAdd.map((v) => ({ label: v }))];
          await api.put(`/fields/${g.field.id}/options`, { options });
        }
        // a grade valida no cliente com os campos já carregados na página (query "form"); sem invalidar,
        // ela continuaria acusando erro nas opções que acabamos de adicionar no servidor.
        await qc.invalidateQueries({ queryKey: ["form", generatorId] });
        const revalidated = await api.post<{ invalid_count: number }>(
          `/generators/${generatorId}/batch/validate`,
          { rows: pending.rows },
        );
        onImported({ rows: pending.rows, mode, invalid: revalidated.invalid_count });
      } else {
        onImported({ rows: pending.rows, mode, invalid: pending.validation.invalid_count });
      }
      setUnknowns(null);
      setPending(null);
      onOpenChange(false);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const used = new Set(mapping.filter(Boolean));
  const unmapped = preview?.fields.filter((f) => !used.has(f.name)) ?? [];
  const unmappedRequired = unmapped.filter((f) => f.required);

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={unknowns ? "Valores novos nas listas de opções" : preview ? "Mapear colunas" : "Importar planilha"}
      description={
        unknowns
          ? "Algumas células têm valores que ainda não existem nas opções dos campos. Quer adicioná-los como opções?"
          : preview
            ? `${preview.row_count} linhas em “${preview.filename}”. Confirme para qual campo vai cada coluna.`
            : "Envie um arquivo .xlsx ou .csv (até 10 MB). A primeira linha deve ter os nomes das colunas — de preferência os mesmos nomes dos campos."
      }
      size="xl"
      footer={
        unknowns ? (
          <>
            <Button loading={busy} onClick={() => resolveUnknowns(false)}>Não adicionar (manter erro)</Button>
            <Button variant="primary" loading={busy} onClick={() => resolveUnknowns(true)} data-testid="import-add-options">
              Adicionar {unknowns.reduce((n, g) => n + g.selected.size, 0)} opção(ões) e continuar
            </Button>
          </>
        ) : preview ? (
          <>
            <Button onClick={() => setPreview(null)}>Trocar arquivo</Button>
            <Button variant="primary" loading={busy} disabled={mapping.every((m) => !m)} onClick={apply} data-testid="import-apply">
              Importar {preview.row_count} linhas
            </Button>
          </>
        ) : (
          <Button onClick={() => onOpenChange(false)}>Cancelar</Button>
        )
      }
    >
      {error && <Alert tone="danger" className="mb-3">{error}</Alert>}
      {unknowns ? (
        <div className="space-y-4" data-testid="import-unknown-options">
          {unknowns.map((g) => (
            <div key={g.field.name} className="rounded-md border border-border p-3">
              <p className="mb-2 text-sm font-medium">{g.field.label}</p>
              {(g.field.options?.length ?? 0) > 0 && (
                <div className="mb-2 flex flex-wrap gap-1.5">
                  <span className="text-xs text-muted">Opções atuais:</span>
                  {g.field.options!.map((o) => (
                    <Badge key={o.value}>{o.label}</Badge>
                  ))}
                </div>
              )}
              <div className="space-y-1.5">
                {g.newValues.map((v) => (
                  <Checkbox
                    key={v}
                    label={<>Adicionar “{v}” como nova opção</>}
                    checked={g.selected.has(v)}
                    onChange={() => toggleUnknownValue(g.field.name, v)}
                  />
                ))}
              </div>
            </div>
          ))}
          <Alert tone="neutral">
            Valores desmarcados continuam como erro na planilha — dá para corrigir a célula ou adicionar a opção depois, na etapa Campos.
          </Alert>
        </div>
      ) : !preview ? (
        <label
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault(); // sem isso o navegador abriria o arquivo e a pessoa sairia da tela
            const f = e.dataTransfer.files[0];
            if (f && !busy) upload(f);
          }}
          className="flex cursor-pointer flex-col items-center gap-3 rounded-lg border-2 border-dashed border-border-strong bg-surface-2 px-6 py-12 text-center hover:border-primary has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-primary"
        >
          <UploadCloud className="h-9 w-9 text-muted" aria-hidden />
          <span className="text-sm text-muted" role="status">{busy ? "Lendo o arquivo…" : file ? `${file.name} (${formatBytes(file.size)})` : "Arraste ou escolha um arquivo .xlsx ou .csv"}</span>
          <span className="inline-flex h-10 items-center rounded-md border border-border-strong bg-surface px-4 text-sm font-medium">Escolher arquivo</span>
          <input type="file" data-testid="import-input" accept=".xlsx,.csv,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" className="sr-only" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        </label>
      ) : (
        <div className="space-y-4">
          <div className="relative overflow-x-auto rounded-md border border-border">
            <table className="w-full min-w-[640px] text-left text-sm">
              <caption className="sr-only">Mapeamento das colunas do arquivo</caption>
              <thead className="bg-surface-2 text-xs uppercase tracking-wide text-muted">
                <tr>
                  <th scope="col" className="px-3 py-2">Coluna do arquivo</th>
                  <th scope="col" className="px-3 py-2">Exemplos</th>
                  <th scope="col" className="px-3 py-2">Vai para o campo</th>
                </tr>
              </thead>
              <tbody>
                {preview.columns.map((col, i) => (
                  <tr key={i} className="border-t border-border">
                    <th scope="row" className="px-3 py-2 font-medium">
                      <FileSpreadsheet className="mr-1 inline h-3.5 w-3.5 text-muted" aria-hidden />
                      {col}
                    </th>
                    <td className="max-w-64 truncate px-3 py-2 text-muted">{preview.sample.map((r) => r[i]).filter(Boolean).slice(0, 3).join(" · ")}</td>
                    <td className="px-3 py-2">
                      <Select aria-label={`Campo para a coluna ${col}`} value={mapping[i] ?? ""} onChange={(e) => setMapping((m) => m.map((x, k) => (k === i ? e.target.value || null : x)))} className="h-9" data-testid={`map-${i}`}>
                        <option value="">— Ignorar esta coluna —</option>
                        {preview.fields.map((f) => (
                          <option key={f.name} value={f.name} disabled={used.has(f.name) && mapping[i] !== f.name}>
                            {f.label}
                            {f.required ? " *" : ""}
                          </option>
                        ))}
                      </Select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {unmappedRequired.length > 0 && (
            <Alert tone="warning" title="Campos obrigatórios sem coluna">
              {unmappedRequired.map((f) => f.label).join(", ")}. As células ficarão vazias (ou com o valor padrão) e serão apontadas como erro.
            </Alert>
          )}
          <fieldset className="flex flex-wrap gap-4">
            <legend className="sr-only">Destino das linhas</legend>
            {(
              [["replace", "Substituir as linhas atuais"], ["append", "Acrescentar ao final"]] as const
            ).map(([v, t]) => (
              <label key={v} className="flex cursor-pointer items-center gap-2 text-sm">
                <input type="radio" name="import-mode" checked={mode === v} onChange={() => setMode(v)} className="accent-[var(--primary)]" />
                {t}
              </label>
            ))}
          </fieldset>
        </div>
      )}
    </Dialog>
  );
}
