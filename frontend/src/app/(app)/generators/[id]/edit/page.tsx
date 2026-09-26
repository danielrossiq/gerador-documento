"use client";

import type { JSONContent } from "@tiptap/core";
import { EditorContent, useEditor, useEditorState } from "@tiptap/react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, ArrowRight, Check, History, Loader2, Menu, Plus, Redo2, Sparkles, Undo2 } from "lucide-react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BubbleToolbar, selectionForField, type PendingSelection } from "@/components/editor/bubble-toolbar";
import { FieldsContext } from "@/components/editor/context";
import { DeleteFieldDialog, VersionsDialog } from "@/components/editor/dialogs";
import { buildOutline, countFieldNodes, fieldNodes, rangeOfOffsets, scrollToPos, type OutlineItem } from "@/components/editor/doc-utils";
import { buildExtensions, findMatches, highlightKey } from "@/components/editor/extensions";
import { FieldForm } from "@/components/editor/field-form";
import { LeftSidebar } from "@/components/editor/left-sidebar";
import { SuggestionsPanel } from "@/components/editor/suggestions-panel";
import { useAutosave } from "@/components/editor/use-autosave";
import { ModelNav } from "@/components/models/model-nav";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { Alert, Skeleton } from "@/components/ui/misc";
import { TabPanel, Tabs } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { detectType, guessLabel } from "@/lib/fields/masks";
import type { EditorPayload, FieldOut, FieldType, GeneratorOut, SuggestionGroup, VersionOut } from "@/lib/types";
import { cn } from "@/lib/utils";

type Creating = { from: number; to: number; text: string; type: FieldType; label: string } | null;

function EditorView({ initial }: { initial: EditorPayload }) {
  const router = useRouter();
  const toast = useToast();
  const params = useSearchParams();
  const id = initial.generator.id;

  const [generator, setGenerator] = useState<GeneratorOut>(initial.generator);
  const [version, setVersion] = useState<VersionOut>(initial.version);
  const [fields, setFields] = useState<FieldOut[]>(initial.fields);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState<Creating>(null);
  const [rightTab, setRightTab] = useState(params.get("panel") === "suggestions" ? "suggestions" : "field");
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [outline, setOutline] = useState<OutlineItem[]>([]);
  const [search, setSearch] = useState("");
  const [matchIdx, setMatchIdx] = useState(0);
  const [matchTotal, setMatchTotal] = useState(0);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [toDelete, setToDelete] = useState<FieldOut | null>(null);
  const [name, setName] = useState(initial.generator.name);
  const occIdx = useRef<Record<string, number>>({});

  // callbacks estáveis para as extensões (o editor é criado uma única vez)
  const markDirtyRef = useRef<() => void>(() => {});
  const openFieldRef = useRef<(fid: string) => void>(() => {});
  const shortcutRef = useRef<() => void>(() => {});
  const extensions = useMemo(
    () => buildExtensions({ onOpenField: (fid) => openFieldRef.current(fid), onFieldShortcut: () => shortcutRef.current() }),
    [],
  );

  const refreshDerived = useRef<ReturnType<typeof setTimeout> | null>(null);
  const editor = useEditor({
    extensions,
    content: initial.doc as JSONContent,
    immediatelyRender: false,
    editorProps: { attributes: { role: "textbox", "aria-multiline": "true", "aria-label": "Conteúdo do documento", spellcheck: "false" } },
    onUpdate: ({ editor: e, transaction }) => {
      if (transaction.docChanged) markDirtyRef.current();
      if (refreshDerived.current) clearTimeout(refreshDerived.current);
      refreshDerived.current = setTimeout(() => {
        setCounts(countFieldNodes(e.state.doc));
        setOutline(buildOutline(e.state.doc));
      }, 250);
    },
    onCreate: ({ editor: e }) => {
      setCounts(countFieldNodes(e.state.doc));
      setOutline(buildOutline(e.state.doc));
    },
  });

  const autosave = useAutosave(editor, id, initial.version.revision);
  markDirtyRef.current = autosave.markDirty;

  const fieldsView = useMemo(() => fields.map((f) => ({ ...f, occurrences: counts[f.id] ?? 0, missing_in_document: !(counts[f.id] > 0) })), [fields, counts]);
  const fieldMap = useMemo(() => Object.fromEntries(fieldsView.map((f) => [f.id, f])), [fieldsView]);
  const selectedField = selectedId ? fieldMap[selectedId] : null;

  const editorState = useEditorState({ editor, selector: ({ editor: e }) => ({ canUndo: !!e?.can().undo(), canRedo: !!e?.can().redo() }) });

  // ---- realces (busca e sugestões)
  const setHighlights = useCallback((ranges: { from: number; to: number }[]) => {
    if (!editor) return;
    editor.view.dispatch(editor.state.tr.setMeta(highlightKey, { ranges }));
  }, [editor]);

  useEffect(() => {
    if (!editor) return;
    editor.view.dispatch(editor.state.tr.setMeta(highlightKey, { query: search, current: 0 }));
    setMatchIdx(0);
    setMatchTotal(search.trim().length >= 2 ? findMatches(editor.state.doc, search).length : 0);
  }, [search, editor]);

  const navMatch = (d: -1 | 1) => {
    if (!editor || !matchTotal) return;
    const next = (matchIdx + d + matchTotal) % matchTotal;
    setMatchIdx(next);
    editor.view.dispatch(editor.state.tr.setMeta(highlightKey, { current: next }));
    const m = findMatches(editor.state.doc, search)[next];
    if (m) scrollToPos(editor, m.from);
  };

  // ---- seleção de campos e ocorrências
  const selectField = useCallback((fid: string, jump = false) => {
    setSelectedId(fid);
    setCreating(null);
    setRightTab("field");
    setDrawer(true);
    if (jump && editor) {
      const first = fieldNodes(editor.state.doc, fid)[0];
      if (first) {
        occIdx.current[fid] = 0;
        editor.chain().setNodeSelection(first.pos).run();
        scrollToPos(editor, first.pos);
      }
    }
  }, [editor]);
  openFieldRef.current = (fid) => selectField(fid);

  const navOccurrence = (fid: string, d: -1 | 1) => {
    if (!editor) return;
    const nodes = fieldNodes(editor.state.doc, fid);
    if (!nodes.length) return;
    const i = ((occIdx.current[fid] ?? 0) + d + nodes.length) % nodes.length;
    occIdx.current[fid] = i;
    editor.chain().setNodeSelection(nodes[i].pos).run();
    scrollToPos(editor, nodes[i].pos);
  };

  // ---- criar campo a partir da seleção (ou no cursor)
  const startCreate = useCallback((sel: PendingSelection | null) => {
    if (!editor) return;
    const cursor = editor.state.selection.from;
    const type = sel ? detectType(sel.text) : "text_short";
    setCreating({
      from: sel?.from ?? cursor, to: sel?.to ?? cursor, text: sel?.text ?? "", type,
      label: sel ? guessLabel(sel.before, type, sel.text) : "",
    });
    setSelectedId(null);
    setRightTab("field");
    setDrawer(true);
  }, [editor]);
  shortcutRef.current = () => {
    const s = editor ? selectionForField(editor) : null;
    if (s) startCreate(s);
    else toast.push({ tone: "info", title: "Selecione um trecho de texto", description: "Marque, dentro de um parágrafo, o trecho que muda de documento para documento." });
  };

  function insertChip(f: FieldOut, range?: { from: number; to: number; text: string }) {
    if (!editor) return;
    let from = range?.from ?? editor.state.selection.from;
    let to = range?.to ?? editor.state.selection.from;
    let sample = range?.text ?? "";
    if (range && editor.state.doc.textBetween(from, to, "\n", "￼") !== range.text) {
      const cur = selectionForField(editor); // o documento mudou desde a seleção: usa a seleção atual se ainda for o mesmo texto
      if (cur && cur.text === range.text) ({ from, to } = cur);
      else {
        from = to = editor.state.selection.from;
        sample = "";
      }
    }
    const marks = (editor.state.doc.nodeAt(from)?.marks ?? []).map((m) => ({ type: m.type.name }));
    editor.chain().focus().insertContentAt({ from, to }, { type: "field", attrs: { fieldId: f.id, sample }, marks }).run();
  }

  function onCreated(f: FieldOut) {
    if (creating) insertChip(f, creating.text ? { from: creating.from, to: creating.to, text: creating.text } : undefined);
    setFields((fs) => [...fs, f]);
    setCounts(editor ? countFieldNodes(editor.state.doc) : counts);
    setCreating(null);
    setSelectedId(f.id);
    toast.push({ tone: "success", title: `Campo “${f.label}” criado` });
  }

  // ---- recarregar do servidor (após excluir campo / aceitar sugestões / restaurar versão)
  const reloadFromServer = useCallback(async () => {
    const p = await api.get<EditorPayload>(`/generators/${id}/editor`);
    editor?.commands.setContent(p.doc as JSONContent, { emitUpdate: false });
    autosave.reset(p.version.revision);
    setFields(p.fields);
    setVersion(p.version);
    setGenerator(p.generator);
    if (editor) {
      setCounts(countFieldNodes(editor.state.doc));
      setOutline(buildOutline(editor.state.doc));
    }
  }, [id, editor, autosave]);

  async function confirmDelete(mode: "keep_text" | "remove_text") {
    if (!toDelete) return;
    try {
      if (!(await autosave.flush())) throw new Error("Não foi possível salvar as alterações pendentes.");
      await api.delete(`/fields/${toDelete.id}?occurrences=${mode}`);
      await reloadFromServer();
      setSelectedId(null);
      toast.push({ tone: "success", title: `Campo “${toDelete.label}” excluído`, description: mode === "keep_text" ? "O texto original foi mantido no documento." : "O trecho foi removido do documento." });
      setToDelete(null);
    } catch (e) {
      toast.push({ tone: "danger", title: "Não foi possível excluir", description: errorMessage(e) });
    }
  }

  async function moveField(fid: string, dir: -1 | 1) {
    const i = fields.findIndex((f) => f.id === fid);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= fields.length) return;
    const next = [...fields];
    [next[i], next[j]] = [next[j], next[i]];
    setFields(next);
    try {
      await api.put(`/generators/${id}/fields/order`, { ids: next.map((f) => f.id) });
    } catch (e) {
      setFields(fields);
      toast.push({ tone: "danger", title: "Não foi possível reordenar", description: errorMessage(e) });
    }
  }

  async function goBack() {
    if (!(await autosave.flush())) {
      if (!window.confirm("Há alterações que não foram salvas. Sair mesmo assim?")) return;
    }
    router.push("/dashboard");
  }
  async function goTo(href: string) {
    if (!(await autosave.flush())) return toast.push({ tone: "danger", title: "Salve as alterações antes de sair do editor", description: autosave.message ?? undefined });
    router.push(href);
  }
  const goUse = () => goTo(`/generators/${id}/use`);

  async function saveName() {
    const n = name.trim();
    if (!n || n === generator.name) return setName(generator.name);
    try {
      setGenerator(await api.patch<GeneratorOut>(`/generators/${id}`, { name: n }));
    } catch (e) {
      toast.push({ tone: "danger", title: "Não foi possível renomear", description: errorMessage(e) });
      setName(generator.name);
    }
  }

  const locateOccurrence = useCallback((o: SuggestionGroup["occurrences"][number]) => {
    if (!editor) return;
    const r = rangeOfOffsets(editor, o.block_key, o.start, o.end);
    if (!r) return;
    editor.chain().setTextSelection(r).run();
    scrollToPos(editor, r.from);
  }, [editor]);
  const highlightOccurrences = useCallback((occ: SuggestionGroup["occurrences"] | null) => {
    if (!editor) return;
    setHighlights(occ ? occ.map((o) => rangeOfOffsets(editor, o.block_key, o.start, o.end)).filter((r): r is { from: number; to: number } => !!r) : []);
  }, [editor, setHighlights]);

  const goOutline = (o: OutlineItem) => {
    if (!editor) return;
    let target: number | null = null;
    editor.state.doc.descendants((n, pos) => {
      if (target !== null) return false;
      if ((o.kind === "part" && n.type.name === "docPart" && `part:${n.attrs.part}` === o.key) || (o.kind !== "part" && n.attrs.blockKey === o.key)) target = pos + 1;
      return true;
    });
    if (target !== null) scrollToPos(editor, target);
  };

  const ctxValue = useMemo(() => ({ fields: fieldMap, selectedId, select: (fid: string) => selectField(fid) }), [fieldMap, selectedId, selectField]);
  const pendingSuggestions = useQuery({ queryKey: ["suggestions", id], queryFn: () => api.get<{ items: unknown[] }>(`/generators/${id}/suggestions`), staleTime: 5000 });
  const nSuggestions = pendingSuggestions.data?.items.length ?? 0;
  // ao reabrir um modelo com sugestões pendentes, elas são o próximo passo — abre direto nelas (uma vez).
  // Ajuste de estado durante a renderização (padrão do React para "derivar do anterior"), sem efeito.
  const [autoTabDone, setAutoTabDone] = useState(false);
  if (!autoTabDone && pendingSuggestions.isSuccess) {
    setAutoTabDone(true);
    if (nSuggestions > 0 && !selectedId && !creating) setRightTab("suggestions");
  }

  const SaveBadge = (() => {
    const s = autosave.state;
    const base = "flex items-center gap-1.5 text-sm";
    if (s === "saving") return <span className={cn(base, "text-muted")}><Loader2 className="h-4 w-4 animate-spin" aria-hidden />Salvando…</span>;
    if (s === "dirty") return <span className={cn(base, "text-muted")}><span className="h-2 w-2 rounded-full bg-warning" aria-hidden />Alterações pendentes</span>;
    if (s === "error") return <span className={cn(base, "text-danger")}><AlertTriangle className="h-4 w-4" aria-hidden />Erro ao salvar<button type="button" className="ml-1 underline" onClick={autosave.retry}>Tentar novamente</button></span>;
    if (s === "conflict") return <span className={cn(base, "text-danger")}><AlertTriangle className="h-4 w-4" aria-hidden />Alterado em outro lugar<button type="button" className="ml-1 underline" onClick={() => location.reload()}>Recarregar</button></span>;
    return <span className={cn(base, "text-success")}><Check className="h-4 w-4" aria-hidden />Salvo</span>;
  })();

  return (
    <FieldsContext.Provider value={ctxValue}>
      <div className="flex h-screen flex-col bg-bg">
        <header className="flex flex-wrap items-center gap-2 border-b border-border bg-surface px-3 py-2">
          <Button variant="ghost" size="icon" aria-label="Voltar ao painel" onClick={goBack}>
            <ArrowLeft className="h-4 w-4" aria-hidden />
          </Button>
          <div className="min-w-0 flex-1 sm:max-w-md">
            <label htmlFor="gen-name" className="sr-only">Nome do modelo</label>
            <Input id="gen-name" value={name} onChange={(e) => setName(e.target.value)} onBlur={saveName} onKeyDown={(e) => e.key === "Enter" && (e.currentTarget as HTMLInputElement).blur()} className="h-9 border-transparent bg-transparent font-semibold hover:border-border-strong" />
          </div>
          <div aria-live="polite" role="status" data-testid="save-state" data-state={autosave.state} className="min-w-36">{SaveBadge}</div>
          <div className="ml-auto flex flex-wrap items-center gap-1.5">
            <Button variant="ghost" size="icon" aria-label="Desfazer" title="Desfazer (Ctrl+Z)" disabled={!editorState?.canUndo} onClick={() => editor?.chain().focus().undo().run()}>
              <Undo2 className="h-4 w-4" aria-hidden />
            </Button>
            <Button variant="ghost" size="icon" aria-label="Refazer" title="Refazer (Ctrl+Shift+Z)" disabled={!editorState?.canRedo} onClick={() => editor?.chain().focus().redo().run()}>
              <Redo2 className="h-4 w-4" aria-hidden />
            </Button>
            <Button variant="ghost" onClick={() => startCreate(null)} title="Cria um campo e o insere onde está o cursor">
              <Plus className="h-4 w-4" aria-hidden /> <span className="hidden xl:inline">Campo no cursor</span>
            </Button>
            <Button variant="ghost" onClick={() => setVersionsOpen(true)} title="Histórico de versões do documento">
              <History className="h-4 w-4" aria-hidden /> <span className="hidden xl:inline">Versões</span>
            </Button>
            <ModelNav id={id} current="edit" onNavigate={goTo} className="ml-1" />
            <Button className="lg:hidden" size="icon" aria-label="Abrir painel de campos e sugestões" onClick={() => setDrawer((d) => !d)}>
              <Menu className="h-4 w-4" aria-hidden />
            </Button>
          </div>
        </header>
        <div className="border-b border-warning/30 bg-warning-soft px-4 py-1.5 text-xs text-warning lg:hidden">
          A edição avançada funciona melhor em telas maiores (desktop). Geração individual funciona em qualquer tela.
        </div>

        <div className="relative flex min-h-0 flex-1">
          <div className="hidden lg:flex">
            <LeftSidebar
              collapsed={leftCollapsed} onToggle={() => setLeftCollapsed((c) => !c)} fields={fieldsView} selectedId={selectedId}
              onSelect={(f) => selectField(f.id, true)} onInsert={(f) => insertChip(f)} onMove={moveField}
              outline={outline} onGoOutline={goOutline} search={search} onSearch={setSearch} matches={matchTotal} matchIndex={matchIdx} onMatchNav={navMatch}
            />
          </div>

          <main id="main" className="doc-canvas min-w-0 flex-1 overflow-y-auto px-4 py-8" aria-label="Documento" tabIndex={-1}>
            {initial.warnings.length > 0 && (
              <div className="mx-auto mb-4 max-w-[794px]">
                <Alert tone="neutral">{initial.warnings.join(" ")}</Alert>
              </div>
            )}
            <div className="doc-page" data-testid="doc-page">
              <EditorContent editor={editor} />
            </div>
            <p className="mx-auto mt-4 max-w-[794px] text-center text-xs text-muted">
              Visual contínuo: a paginação real acontece ao gerar o DOCX/PDF. Selecione um trecho e use <kbd className="rounded border border-border bg-surface px-1">Ctrl</kbd>+<kbd className="rounded border border-border bg-surface px-1">Shift</kbd>+<kbd className="rounded border border-border bg-surface px-1">F</kbd> para transformá-lo em campo.
            </p>
          </main>

          <aside
            aria-label="Propriedades"
            className={cn(
              "z-40 flex w-[min(26rem,100vw)] shrink-0 flex-col border-l border-border bg-surface",
              "fixed inset-y-0 right-0 transition-transform lg:static lg:translate-x-0",
              drawer ? "translate-x-0" : "translate-x-full",
            )}
          >
            <Tabs
              value={rightTab}
              onValueChange={setRightTab}
              className="flex min-h-0 flex-1 flex-col"
              tabs={[
                { value: "field", label: "Campo" },
                { value: "suggestions", label: <span className="inline-flex items-center gap-1"><Sparkles className="h-3.5 w-3.5" aria-hidden />Sugestões{nSuggestions ? ` (${nSuggestions})` : ""}</span> },
                { value: "document", label: "Documento" },
              ]}
            >
              <TabPanel value="field" className="min-h-0 flex-1 overflow-y-auto p-4">
                {creating ? (
                  <>
                    <h2 className="mb-3 text-base font-semibold">Novo campo</h2>
                    <FieldForm
                      key={`new-${creating.from}-${creating.to}`}
                      mode="create" generatorId={id}
                      seed={{ label: creating.label, type: creating.type, example: creating.text, text: creating.text || undefined }}
                      onCreated={onCreated} onCancel={() => setCreating(null)}
                    />
                    {fields.length > 0 && creating.text && (
                      <details className="mt-4 rounded-md border border-border p-3">
                        <summary className="cursor-pointer text-sm font-medium">Ou usar um campo que já existe</summary>
                        <ul className="mt-2 space-y-1">
                          {fieldsView.map((f) => (
                            <li key={f.id}>
                              <button
                                type="button"
                                className="w-full rounded px-2 py-1.5 text-left text-sm hover:bg-surface-2"
                                onClick={() => {
                                  insertChip(f, { from: creating.from, to: creating.to, text: creating.text });
                                  setCreating(null);
                                  setSelectedId(f.id);
                                }}
                              >
                                {f.label}
                              </button>
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </>
                ) : selectedField ? (
                  <>
                    <h2 className="mb-3 text-base font-semibold">Configurar campo</h2>
                    <FieldForm
                      key={selectedField.id} mode="edit" generatorId={id} field={selectedField}
                      occurrenceNav={{ count: selectedField.occurrences, onPrev: () => navOccurrence(selectedField.id, -1), onNext: () => navOccurrence(selectedField.id, 1) }}
                      onChanged={(f) => setFields((fs) => fs.map((x) => (x.id === f.id ? { ...x, ...f } : x)))}
                      onDelete={() => setToDelete(selectedField)}
                    />
                  </>
                ) : (
                  <div className="space-y-4 text-sm text-muted">
                    {fields.length > 0 && <NextStepCard count={fields.length} onGo={goUse} />}
                    <div className="space-y-3">
                      <h2 className="text-base font-semibold text-fg">Como marcar um trecho que muda</h2>
                      <ol className="list-decimal space-y-1 pl-5">
                        <li>Selecione o texto no documento (ex.: um nome).</li>
                        <li>Clique em <strong className="text-fg">Transformar em campo</strong> no menu que aparece.</li>
                        <li>Dê um nome ao campo — ele vira uma pergunta no formulário.</li>
                      </ol>
                      <p className="text-xs">
                        Atalho: <kbd className="rounded border border-border px-1">Ctrl</kbd>+<kbd className="rounded border border-border px-1">Shift</kbd>+<kbd className="rounded border border-border px-1">F</kbd> · Clique num campo já criado para configurá-lo.
                      </p>
                    </div>
                  </div>
                )}
              </TabPanel>

              <TabPanel value="suggestions" className="min-h-0 flex-1 overflow-y-auto p-4">
                <SuggestionsPanel
                  generatorId={id} analysisStatus={version.analysis_status}
                  beforeApply={autosave.flush}
                  onApplied={async () => reloadFromServer()}
                  onHighlight={highlightOccurrences} onLocate={locateOccurrence}
                  next={fields.length > 0 ? <NextStepCard count={fields.length} onGo={goUse} /> : null}
                />
              </TabPanel>

              <TabPanel value="document" className="min-h-0 flex-1 overflow-y-auto p-4">
                <DocumentPanel generator={generator} stats={initial.stats} onChange={setGenerator} />
              </TabPanel>
            </Tabs>
          </aside>
          {drawer && <button type="button" aria-label="Fechar painel" className="fixed inset-0 z-30 bg-black/30 lg:hidden" onClick={() => setDrawer(false)} />}
        </div>

        {editor && <BubbleToolbar editor={editor} onTransform={startCreate} />}
        <VersionsDialog open={versionsOpen} onOpenChange={setVersionsOpen} generatorId={id} onRestored={reloadFromServer} />
        <DeleteFieldDialog field={toDelete} open={!!toDelete} onOpenChange={(o) => !o && setToDelete(null)} onConfirm={confirmDelete} />
      </div>
    </FieldsContext.Provider>
  );
}

/** O passo seguinte do fluxo, sempre visível no painel — antes, depois de criar campos, ninguém sabia para onde ir. */
function NextStepCard({ count, onGo }: { count: number; onGo: () => void }) {
  return (
    <div className="flex items-center gap-3 rounded-md border border-success/30 bg-success-soft p-3" data-testid="next-step">
      <Check className="h-5 w-5 shrink-0 text-success" aria-hidden />
      <p className="min-w-0 flex-1 text-sm text-fg">
        <strong>{count} {count === 1 ? "campo pronto" : "campos prontos"}.</strong> Já dá para gerar documentos.
      </p>
      <Button size="sm" variant="primary" onClick={onGo}>
        Preencher <ArrowRight className="h-3.5 w-3.5" aria-hidden />
      </Button>
    </div>
  );
}

function DocumentPanel({ generator, stats, onChange }: { generator: GeneratorOut; stats: Record<string, number>; onChange: (g: GeneratorOut) => void }) {
  const toast = useToast();
  const [desc, setDesc] = useState(generator.description ?? "");
  const [pattern, setPattern] = useState(generator.filename_pattern);
  async function save(patch: Record<string, unknown>) {
    try {
      onChange(await api.patch<GeneratorOut>(`/generators/${generator.id}`, patch));
    } catch (e) {
      toast.push({ tone: "danger", title: "Não foi possível salvar", description: errorMessage(e) });
    }
  }
  return (
    <div className="space-y-4">
      <h2 className="text-base font-semibold">Propriedades do documento</h2>
      <Field label="Descrição">{(a) => <Input {...a} value={desc} onChange={(e) => setDesc(e.target.value)} onBlur={() => desc !== (generator.description ?? "") && save({ description: desc })} />}</Field>
      <Field label="Padrão do nome do arquivo" help="Use {nome_tecnico_do_campo}, {hoje}, {linha} ou {gerador}. Ex.: Contrato_{nome_do_contratante}_{hoje}">
        {(a) => <Input className="font-mono text-xs" {...a} value={pattern} onChange={(e) => setPattern(e.target.value)} onBlur={() => pattern !== generator.filename_pattern && pattern.trim() && save({ filename_pattern: pattern })} />}
      </Field>
      <dl className="grid grid-cols-2 gap-2 text-sm">
        {[["Parágrafos", stats.paragraphs], ["Tabelas", stats.tables], ["Imagens", stats.images], ["Cabeçalhos", stats.headers], ["Rodapés", stats.footers], ["Elementos preservados", stats.atoms]].map(([k, v]) => (
          <div key={String(k)} className="rounded-md border border-border p-2">
            <dt className="text-xs text-muted">{k}</dt>
            <dd className="font-semibold tabular-nums">{v ?? 0}</dd>
          </div>
        ))}
      </dl>
      <Alert tone="neutral" title="O que não é editável aqui">
        Imagens, quebras de página, campos do Word e tabelas (estrutura) são preservados no lugar, mas só o texto pode ser alterado.
      </Alert>
    </div>
  );
}

function EditorLoader() {
  const { id } = useParams<{ id: string }>();
  const q = useQuery({
    queryKey: ["editor", id],
    queryFn: () => api.get<EditorPayload>(`/generators/${id}/editor`),
    staleTime: Infinity,
    gcTime: 0,
    retry: false,
    refetchOnMount: "always",
  });
  if (q.isLoading) {
    return (
      <div className="p-6" aria-busy="true">
        <Skeleton className="mb-4 h-10 w-80" />
        <Skeleton className="h-[70vh] w-full max-w-3xl" />
      </div>
    );
  }
  if (q.error) {
    const e = q.error as ApiError;
    return (
      <main id="main" className="mx-auto max-w-lg p-8">
        <Alert tone="danger" title={e.code === "NOT_FOUND" ? "Modelo não encontrado" : "Não foi possível abrir o editor"}>
          {e.code === "NOT_FOUND" ? "Este gerador ainda não tem um arquivo .docx. Volte ao painel e use “Novo gerador” ou envie o arquivo." : errorMessage(e)}
        </Alert>
      </main>
    );
  }
  return <EditorView initial={q.data!} />;
}

export default function EditorPage() {
  return (
    <Suspense>
      <EditorLoader />
    </Suspense>
  );
}
