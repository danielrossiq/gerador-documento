"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowDownToLine, CheckCircle2, ClipboardList, Copy, Download, Eraser, Filter, Layers, MoreHorizontal, PencilRuler, Plus, Redo2, Search, Trash2, Undo2, Upload, Wand2 } from "lucide-react";
import { useParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { BatchGrid, type GridHandle, type GridSpec } from "@/components/batch/grid";
import { gridReducer, initialState, isBlank, newRow, type Row } from "@/components/batch/grid-state";
import { ImportDialog, type ImportResult } from "@/components/batch/import-dialog";
import { RunDialog } from "@/components/batch/run-dialog";
import { GenerateModeTabs, GeneratorHeader, stepHrefs } from "@/components/generators/steps";
import { AppShell, useMe } from "@/components/layout/app-shell";
import { Button, ButtonAnchor, ButtonLink } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/form";
import { ActionMenu } from "@/components/ui/menu";
import { Alert, Badge, EmptyState, Skeleton } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { displayFor } from "@/lib/fields/masks";
import { validateRow, type FieldSpec } from "@/lib/fields/normalize";
import { exampleValues } from "@/lib/fields/samples";
import type { FieldOut, FormPayload } from "@/lib/types";
import { cn, plural } from "@/lib/utils";

const toSpec = (f: FieldOut): GridSpec => ({ name: f.name, label: f.label, type: f.type, required: f.required, default_value: f.default_value, options: f.options, config: f.config, mask: f.mask, description: f.description });

function loadRows(key: string): Row[] | null {
  try {
    const raw = localStorage.getItem(key);
    const parsed = raw ? (JSON.parse(raw) as Row[]) : null;
    return parsed && Array.isArray(parsed) && parsed.length ? parsed : null;
  } catch {
    return null;
  }
}

function BatchView({ data, maxRows }: { data: FormPayload; maxRows: number }) {
  const toast = useToast();
  const id = data.generator.id;
  const storageKey = `minuta:batch:${id}`;
  const batchFields = useMemo(() => data.fields.filter((f) => f.include_in_batch), [data.fields]);
  const specs = useMemo(() => batchFields.map(toSpec), [batchFields]);
  const allSpecs: FieldSpec[] = useMemo(() => data.fields.map(toSpec), [data.fields]);
  const names = useMemo(() => specs.map((s) => s.name), [specs]);
  const labels = useMemo(() => Object.fromEntries(data.fields.map((f) => [f.name, f.label])), [data.fields]);

  const [state, dispatch] = useReducer(gridReducer, undefined, () => initialState(loadRows(storageKey) ?? undefined));
  const [serverErrors, setServerErrors] = useState<Map<string, { row: Row; errors: Record<string, string> }>>(new Map());
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "errors" | "valid">("all");
  const [selCount, setSelCount] = useState(1);
  const [importOpen, setImportOpen] = useState(false);
  const [runOpen, setRunOpen] = useState(false);
  const [panelOpen, setPanelOpen] = useState(true);
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const gridRef = useRef<GridHandle>(null);
  const cache = useRef(new WeakMap<Row, Record<string, string>>());

  // rascunho do lote neste navegador (salvamento automático leve)
  useEffect(() => {
    const t = setTimeout(() => {
      try {
        localStorage.setItem(storageKey, JSON.stringify(state.rows));
        if (state.past.length) setSavedAt(new Date());
      } catch {
        /* cota/privacidade: segue sem persistir */
      }
    }, 600);
    return () => clearTimeout(t);
  }, [state.rows, state.past.length, storageKey]);

  const errorsFor = useCallback((row: Row): Record<string, string> => {
    if (isBlank(row)) return {};
    let e = cache.current.get(row);
    if (!e) {
      const inBatch = new Set(names);
      const res = validateRow(allSpecs, Object.fromEntries(Object.entries(row.v).filter(([k]) => inBatch.has(k))));
      e = { ...res.errors };
      for (const f of data.fields) if (!f.include_in_batch && f.required && (f.default_value === null || f.default_value === "")) e[f.name] = "Campo obrigatório que não está na planilha e não tem valor já preenchido. Ajuste-o no editor.";
      cache.current.set(row, e);
    }
    const s = serverErrors.get(row.id);
    return s && s.row === row ? { ...s.errors, ...e } : e;
  }, [allSpecs, names, data.fields, serverErrors]);

  const stats = useMemo(() => {
    let total = 0, invalid = 0;
    const list: { rowIndex: number; name: string; label: string; message: string }[] = [];
    state.rows.forEach((r, i) => {
      if (isBlank(r)) return;
      total++;
      const errs = errorsFor(r);
      const keys = Object.keys(errs);
      if (keys.length) {
        invalid++;
        if (list.length < 400) for (const k of keys) list.push({ rowIndex: i, name: k, label: labels[k] ?? k, message: errs[k] });
      }
    });
    return { total, invalid, valid: total - invalid, list };
  }, [state.rows, errorsFor, labels]);

  const view = useMemo(() => {
    const q = search.trim().toLowerCase();
    const out: number[] = [];
    state.rows.forEach((r, i) => {
      if (filter !== "all") {
        const blank = isBlank(r);
        const bad = !blank && Object.keys(errorsFor(r)).length > 0;
        if (filter === "errors" && !bad) return;
        if (filter === "valid" && (blank || bad)) return;
      }
      if (q && !Object.values(r.v).some((v) => v.toLowerCase().includes(q))) return;
      out.push(i);
    });
    return out;
  }, [state.rows, filter, search, errorsFor]);

  const sendRows = useMemo(() => state.rows.filter((r) => !isBlank(r)), [state.rows]);

  function goToError(e: { rowIndex: number; name: string }) {
    if (!gridRef.current?.scrollToCell(e.rowIndex, e.name)) {
      setFilter("all");
      setSearch("");
      setTimeout(() => gridRef.current?.scrollToCell(e.rowIndex, e.name), 60);
    }
  }

  function onImported(r: ImportResult) {
    const rows = r.rows.map((raw) => newRow(Object.fromEntries(specs.map((s) => [s.name, displayFor(s, raw[s.name] ?? "")]))));
    dispatch(r.mode === "replace" ? { type: "replace", rows } : { type: "append", rows, max: maxRows });
    toast.push({ tone: r.invalid ? "info" : "success", title: `${plural(rows.length, "linha importada", "linhas importadas")}`, description: r.invalid ? `${plural(r.invalid, "linha tem", "linhas têm")} erro — veja a lista de erros ao lado da planilha.` : "Todas as linhas estão prontas para gerar." });
  }

  function addExampleRow() {
    const sample = exampleValues(data.fields, data.doc);
    const v = Object.fromEntries(specs.map((s) => [s.name, s.name in sample ? displayFor(s, sample[s.name] === true ? "Sim" : String(sample[s.name])) : ""]));
    dispatch({ type: "append", rows: [newRow(v), newRow()], max: maxRows });
    toast.push({ tone: "info", title: "Linha de exemplo adicionada", description: "Use-a como modelo e troque pelos dados reais. Desfazer: Ctrl+Z." });
  }

  function clearAll() {
    dispatch({ type: "replace", rows: [newRow(), newRow(), newRow()] });
    setServerErrors(new Map());
    toast.push({ tone: "info", title: "Planilha limpa", description: "Foi sem querer? Use Desfazer (Ctrl+Z)." });
  }

  const rowsLabel = selCount > 1 ? `${selCount} linhas selecionadas` : "linha selecionada";

  return (
    <>
      {stats.total === 0 && (
        <Alert tone="primary" title="Cada linha vira um documento; cada coluna é um campo" className="mb-3">
          <p>Clique numa célula e digite, cole um intervalo copiado do Excel ou Google Planilhas (<kbd className="rounded border border-border bg-surface px-1">Ctrl</kbd>+<kbd className="rounded border border-border bg-surface px-1">V</kbd>) ou importe um arquivo .xlsx/.csv.</p>
          <div className="mt-2">
            <Button size="sm" onClick={addExampleRow} data-testid="add-example-row"><Wand2 className="h-4 w-4" aria-hidden /> Começar com um exemplo</Button>
          </div>
        </Alert>
      )}

      <div className="mb-3 flex flex-wrap items-center gap-2" role="toolbar" aria-label="Ações da planilha">
        <Button onClick={() => setImportOpen(true)} data-testid="open-import"><Upload className="h-4 w-4" aria-hidden /> Importar planilha</Button>
        <ButtonAnchor href={`/api/v1/generators/${id}/batch/template.xlsx`} download variant="ghost" title="Planilha .xlsx com as colunas certas, listas de opções e instruções">
          <Download className="h-4 w-4" aria-hidden /> <span className="hidden sm:inline">Baixar planilha-modelo</span><span className="sm:hidden">Modelo .xlsx</span>
        </ButtonAnchor>
        <span aria-hidden className="mx-1 hidden h-6 w-px bg-border sm:block" />
        <Button onClick={() => dispatch({ type: "addRows", count: 1, max: maxRows })} data-testid="add-row"><Plus className="h-4 w-4" aria-hidden /> Linha</Button>
        <ActionMenu
          label="Mais ações nas linhas"
          trigger={<Button aria-label="Mais ações nas linhas" data-testid="rows-menu"><MoreHorizontal className="h-4 w-4" aria-hidden /> <span className="hidden sm:inline">Mais</span></Button>}
          items={[
            { label: `Duplicar ${rowsLabel}`, icon: <Copy className="h-4 w-4" aria-hidden />, onSelect: () => dispatch({ type: "duplicate", rows: gridRef.current?.selectedRows() ?? [], max: maxRows }) },
            { label: `Remover ${rowsLabel}`, icon: <Trash2 className="h-4 w-4" aria-hidden />, onSelect: () => dispatch({ type: "remove", rows: gridRef.current?.selectedRows() ?? [] }) },
            { label: "Preencher para baixo (Ctrl+D)", icon: <ArrowDownToLine className="h-4 w-4" aria-hidden />, onSelect: () => gridRef.current?.fillDown() },
            { separator: true },
            { label: "Adicionar linha de exemplo", icon: <Wand2 className="h-4 w-4" aria-hidden />, onSelect: addExampleRow },
            { label: "Limpar a planilha", icon: <Eraser className="h-4 w-4" aria-hidden />, onSelect: clearAll, danger: true, disabled: stats.total === 0 },
          ]}
        />
        <Button variant="ghost" size="icon" aria-label="Desfazer" title="Desfazer (Ctrl+Z)" disabled={!state.past.length} onClick={() => dispatch({ type: "undo" })}><Undo2 className="h-4 w-4" aria-hidden /></Button>
        <Button variant="ghost" size="icon" aria-label="Refazer" title="Refazer (Ctrl+Y)" disabled={!state.future.length} onClick={() => dispatch({ type: "redo" })}><Redo2 className="h-4 w-4" aria-hidden /></Button>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <span className="hidden text-xs text-muted md:inline" aria-live="polite">{stats.total === 0 ? "Preencha ao menos uma linha para gerar." : savedAt ? "Rascunho salvo neste navegador." : ""}</span>
          <Button variant="primary" onClick={() => setRunOpen(true)} disabled={stats.total === 0} title={stats.total === 0 ? "Preencha ao menos uma linha" : undefined} data-testid="open-run">
            <Layers className="h-4 w-4" aria-hidden /> {stats.total ? `Gerar ${plural(stats.total, "documento", "documentos")}` : "Gerar documentos"}
          </Button>
        </div>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2 text-sm" data-testid="counters">
        <span className="sr-only" aria-live="polite">{`${plural(stats.total, "linha preenchida", "linhas preenchidas")}, ${stats.valid} prontas, ${stats.invalid} com erro`}</span>
        <Badge icon={<ClipboardList className="h-3 w-3" aria-hidden />}>{plural(stats.total, "linha preenchida", "linhas preenchidas")}</Badge>
        <button type="button" onClick={() => setFilter(filter === "valid" ? "all" : "valid")} aria-pressed={filter === "valid"} className="rounded-full">
          <Badge tone="success" icon={<CheckCircle2 className="h-3 w-3" aria-hidden />} data-testid="valid-count" className={cn(filter === "valid" && "ring-2 ring-success/40")}>{plural(stats.valid, "pronta", "prontas")}</Badge>
        </button>
        <button type="button" onClick={() => setFilter(filter === "errors" ? "all" : "errors")} aria-pressed={filter === "errors"} className="rounded-full" disabled={!stats.invalid && filter !== "errors"}>
          <Badge tone={stats.invalid ? "danger" : "neutral"} icon={stats.invalid ? <AlertTriangle className="h-3 w-3" aria-hidden /> : undefined} data-testid="invalid-count" className={cn(filter === "errors" && "ring-2 ring-danger/40")}>{plural(stats.invalid, "com erro", "com erro")}</Badge>
        </button>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted" aria-hidden />
            <Input aria-label="Buscar nas linhas" placeholder="Buscar" className="h-9 w-40 pl-9" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          <div className="relative">
            <Filter className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted" aria-hidden />
            <Select aria-label="Mostrar linhas" value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)} className="h-9 w-48 pl-9">
              <option value="all">Todas as linhas</option>
              <option value="errors">Só as com erro</option>
              <option value="valid">Só as prontas</option>
            </Select>
          </div>
          <Button size="sm" variant="ghost" onClick={() => setPanelOpen((p) => !p)} aria-expanded={panelOpen} className="hidden lg:inline-flex">
            {panelOpen ? "Ocultar" : "Mostrar"} lista de erros
          </Button>
        </div>
      </div>

      <div className={panelOpen ? "grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]" : ""}>
        <BatchGrid
          ref={gridRef} specs={specs} rows={state.rows} view={view} errorsFor={errorsFor} blank={isBlank} dispatch={dispatch} maxRows={maxRows}
          onNotice={(msg) => toast.push({ tone: "info", title: msg })} onSelectionChange={setSelCount}
        />
        {panelOpen && (
          <aside aria-label="Lista de erros" tabIndex={0} className="max-h-[calc(100vh-19rem)] min-h-40 overflow-y-auto rounded-lg border border-border bg-surface p-3 lg:h-[calc(100vh-19rem)] lg:min-h-80">
            <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold">
              <AlertTriangle className="h-4 w-4" aria-hidden /> Erros por célula
              {stats.list.length > 0 && <Badge tone="danger">{stats.list.length}{stats.list.length >= 400 ? "+" : ""}</Badge>}
            </h2>
            {stats.list.length === 0 ? (
              <p className="text-sm text-muted">{stats.total ? "Nenhum erro. Tudo pronto para gerar." : "Os erros aparecem aqui assim que você preencher as linhas."}</p>
            ) : (
              <>
                <p className="mb-2 text-xs text-muted">Clique num erro para ir direto à célula; aperte Enter para editar.</p>
                <ul className="space-y-1.5" data-testid="error-list">
                  {stats.list.map((e, i) => (
                    <li key={`${e.rowIndex}-${e.name}-${i}`}>
                      <button type="button" onClick={() => goToError(e)} className="w-full rounded-md border border-danger/30 bg-danger-soft p-2 text-left text-sm hover:border-danger" data-testid="error-item">
                        <span className="font-semibold">Linha {e.rowIndex + 1} · {e.label}</span>
                        <span className="block text-xs text-fg">{e.message}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </aside>
        )}
      </div>
      <p className="mt-2 text-xs text-muted">
        Teclado: setas/Tab navegam, Enter ou F2 editam, Ctrl+C/Ctrl+V copiam e colam, Ctrl+D preenche para baixo. Limite: {maxRows} linhas por lote.
      </p>

      <ImportDialog open={importOpen} onOpenChange={setImportOpen} generatorId={id} hasData={stats.total > 0} onImported={onImported} />
      <RunDialog
        open={runOpen} onOpenChange={setRunOpen} generator={data.generator} fields={data.fields} names={names} rows={sendRows} clientInvalid={stats.invalid}
        pdfAvailable={data.pdf_available}
        onServerErrors={(m) => setServerErrors(new Map([...m].map(([rid, errors]) => [rid, { row: state.rows.find((r) => r.id === rid)!, errors }])))}
        onFocusErrors={() => { setFilter("errors"); setPanelOpen(true); }}
      />
    </>
  );
}

function BatchLoader() {
  const { id } = useParams<{ id: string }>();
  const me = useMe();
  const q = useQuery({ queryKey: ["form", id], queryFn: () => api.get<FormPayload>(`/generators/${id}/form`), retry: false, staleTime: 0 });
  const g = q.data?.generator;
  const noDoc = q.error instanceof ApiError && q.error.code === "NOT_FOUND" && /docx/i.test(q.error.message);
  const h = stepHrefs(id);

  return (
    <AppShell wide>
      {g ? (
        <GeneratorHeader id={id} name={g.name} step="generate" hasTemplate={g.has_template} fieldsCount={q.data!.fields.length} description="Vários documentos de uma vez: preencha uma linha por documento, confira os erros e gere todos juntos.">
          <GenerateModeTabs id={id} current="batch" />
        </GeneratorHeader>
      ) : (
        !q.error && <Skeleton className="mb-6 h-24 w-full" />
      )}
      {q.isLoading || me.isLoading ? (
        <Skeleton className="h-96 w-full" />
      ) : q.error ? (
        <div className="space-y-3">
          <Alert tone={noDoc ? "warning" : "danger"} title={noDoc ? "Falta enviar o documento" : "Não foi possível abrir a planilha"}>
            {noDoc ? "Este gerador ainda não tem o arquivo .docx." : errorMessage(q.error)}
          </Alert>
          <div className="flex flex-wrap gap-2">
            {noDoc ? <ButtonLink href={h.template} variant="primary">Enviar o documento</ButtonLink> : <Button onClick={() => q.refetch()}>Tentar de novo</Button>}
            <ButtonLink href="/dashboard">Voltar aos geradores</ButtonLink>
          </div>
        </div>
      ) : q.data!.fields.length === 0 ? (
        <EmptyState
          icon={<PencilRuler className="h-9 w-9" aria-hidden />}
          title="Este gerador ainda não tem campos"
          description="As colunas da planilha são os campos do gerador. Marque no documento o que muda e volte aqui."
          action={<ButtonLink href={h.fields} variant="primary"><PencilRuler className="h-4 w-4" aria-hidden /> Criar campos</ButtonLink>}
        />
      ) : q.data!.fields.filter((f) => f.include_in_batch).length === 0 ? (
        <EmptyState
          icon={<Layers className="h-9 w-9" aria-hidden />}
          title="Nenhum campo está na planilha"
          description="Todos os campos estão configurados para não aparecer na geração de vários documentos. No editor, abra um campo, clique em “Mais opções” e marque “Pedir também na planilha”."
          action={<ButtonLink href={h.fields} variant="primary"><PencilRuler className="h-4 w-4" aria-hidden /> Ajustar campos</ButtonLink>}
        />
      ) : (
        <BatchView key={id} data={q.data!} maxRows={me.data?.limits?.max_batch_rows ?? 1000} />
      )}
    </AppShell>
  );
}

export default function BatchPage() {
  return (
    <Suspense>
      <BatchLoader />
    </Suspense>
  );
}
