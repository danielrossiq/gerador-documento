"use client";

import type { JSONContent } from "@tiptap/core";
import { EditorContent, useEditor, useEditorState } from "@tiptap/react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, ArrowRight, Check, History, ListChecks, Loader2, Plus, Redo2, Search, Sparkles, Undo2, X } from "lucide-react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BubbleToolbar, selectionForField, type PendingSelection } from "@/components/editor/bubble-toolbar";
import { FieldsContext } from "@/components/editor/context";
import { DeleteFieldDialog, VersionsDialog } from "@/components/editor/dialogs";
import { buildOutline, countFieldNodes, fieldNodes, rangeOfOffsets, scrollToPos, type OutlineItem } from "@/components/editor/doc-utils";
import { buildExtensions, findMatches, highlightKey } from "@/components/editor/extensions";
import { FieldForm, type SaveReport } from "@/components/editor/field-form";
import { FieldList } from "@/components/editor/field-list";
import { DocNavigator } from "@/components/editor/left-sidebar";
import { SuggestionsPanel } from "@/components/editor/suggestions-panel";
import { useAutosave } from "@/components/editor/use-autosave";
import { GeneratorSteps, stepHrefs } from "@/components/generators/steps";
import { Button, ButtonLink } from "@/components/ui/button";
import { Input } from "@/components/ui/form";
import { Alert, Skeleton } from "@/components/ui/misc";
import { TabPanel, Tabs } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { fieldIssues, isDocumentOrder, issuesByField, sortByDocument } from "@/lib/fields/issues";
import { detectType, guessLabel } from "@/lib/fields/masks";
import type { EditorPayload, FieldOut, FieldType, GeneratorOut, SuggestionGroup, VersionOut } from "@/lib/types";
import { cn } from "@/lib/utils";

type Creating = { from: number; to: number; text: string; type: FieldType; label: string } | null;

/** Ids dos campos na ordem da primeira aparição no documento aberto no editor. */
function docOrderOf(doc: Parameters<typeof fieldNodes>[0]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const n of fieldNodes(doc)) {
    if (!seen.has(n.fieldId)) {
      seen.add(n.fieldId);
      out.push(n.fieldId);
    }
  }
  return out;
}

function EditorView({ initial }: { initial: EditorPayload }) {
  const router = useRouter();
  const toast = useToast();
  const params = useSearchParams();
  const id = initial.generator.id;

  const [generator, setGenerator] = useState<GeneratorOut>(initial.generator);
  const [, setVersion] = useState<VersionOut>(initial.version);
  const [fields, setFields] = useState<FieldOut[]>(initial.fields);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [countsReady, setCountsReady] = useState(false); // até o editor montar, "0 ocorrências" não significa "fora do documento"
  // ?field=<id>: vindo da revisão ("Corrigir no editor"), abre direto a configuração desse campo
  const [urlField] = useState<string | null>(() => {
    const f = params.get("field");
    return f && initial.fields.some((x) => x.id === f) ? f : null;
  });
  const [selectedId, setSelectedId] = useState<string | null>(urlField);
  const [creating, setCreating] = useState<Creating>(null);
  const [panel, setPanel] = useState(params.get("panel") === "suggestions" ? "suggestions" : "fields");
  const [navOpen, setNavOpen] = useState(false);
  const [drawer, setDrawer] = useState(!!urlField);
  const [outline, setOutline] = useState<OutlineItem[]>([]);
  const [search, setSearch] = useState("");
  const [matchIdx, setMatchIdx] = useState(0);
  const [matchTotal, setMatchTotal] = useState(0);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [toDelete, setToDelete] = useState<FieldOut | null>(null);
  const [name, setName] = useState(initial.generator.name);
  const [fieldSave, setFieldSave] = useState<SaveReport | null>(null);
  const occIdx = useRef<Record<string, number>>({});
  // A ordem do formulário acompanha a do documento até a pessoa reordenar manualmente.
  const autoOrder = useRef<boolean | null>(null);

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
    editorProps: { attributes: { role: "textbox", "aria-multiline": "true", "aria-label": "Conteúdo do documento. Selecione um trecho para transformá-lo em campo.", spellcheck: "false" } },
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
      setCountsReady(true);
      setOutline(buildOutline(e.state.doc));
      autoOrder.current = isDocumentOrder(initial.fields, docOrderOf(e.state.doc));
      const first = urlField ? fieldNodes(e.state.doc, urlField)[0] : null;
      if (first) {
        e.commands.setNodeSelection(first.pos);
        setTimeout(() => scrollToPos(e, first.pos), 150); // espera o documento estar na tela
      }
    },
  });

  const autosave = useAutosave(editor, id, initial.version.revision);
  markDirtyRef.current = autosave.markDirty;

  const fieldsView = useMemo(() => fields.map((f) => ({ ...f, occurrences: counts[f.id] ?? 0, missing_in_document: !(counts[f.id] > 0) })), [fields, counts]);
  const fieldMap = useMemo(() => Object.fromEntries(fieldsView.map((f) => [f.id, f])), [fieldsView]);
  const issues = useMemo(() => issuesByField(fieldIssues(fieldsView, countsReady ? counts : undefined)), [fieldsView, counts, countsReady]);
  const selectedField = selectedId ? fieldMap[selectedId] : null;
  const inDocOrder = useMemo(() => (editor ? isDocumentOrder(fields, docOrderOf(editor.state.doc)) : true), [fields, editor, counts]); // eslint-disable-line react-hooks/exhaustive-deps

  const editorState = useEditorState({ editor, selector: ({ editor: e }) => ({ canUndo: !!e?.can().undo(), canRedo: !!e?.can().redo() }) });

  // ---- realces (busca, sugestões e trecho em criação)
  const setHighlights = useCallback((meta: Record<string, unknown>) => {
    if (!editor) return;
    editor.view.dispatch(editor.state.tr.setMeta(highlightKey, meta));
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

  // ---- ordem do formulário = ordem do documento (enquanto a pessoa não personalizar)
  const persistOrder = useCallback(async (next: FieldOut[], prev: FieldOut[]) => {
    setFields(next);
    try {
      await api.put(`/generators/${id}/fields/order`, { ids: next.map((f) => f.id) });
    } catch (e) {
      setFields(prev);
      toast.push({ tone: "danger", title: "Não foi possível reordenar", description: errorMessage(e) });
    }
  }, [id, toast]);

  const syncOrder = useCallback((list: FieldOut[]) => {
    if (!editor || !autoOrder.current) return setFields(list);
    const sorted = sortByDocument(list, docOrderOf(editor.state.doc));
    if (sorted.every((f, i) => f.id === list[i].id)) return setFields(list);
    void persistOrder(sorted, list);
  }, [editor, persistOrder]);

  function followDocumentOrder() {
    if (!editor) return;
    autoOrder.current = true;
    void persistOrder(sortByDocument(fields, docOrderOf(editor.state.doc)), fields);
    toast.push({ tone: "success", title: "Formulário na ordem do documento" });
  }

  // ---- seleção de campos e ocorrências
  const stopCreating = useCallback(() => {
    setCreating(null);
    setHighlights({ pending: null });
  }, [setHighlights]);

  const selectField = useCallback((fid: string, jump = false) => {
    setSelectedId(fid);
    stopCreating();
    setPanel("fields");
    setDrawer(true);
    if (jump && editor) {
      const first = fieldNodes(editor.state.doc, fid)[0];
      if (first) {
        occIdx.current[fid] = 0;
        editor.chain().setNodeSelection(first.pos).run();
        scrollToPos(editor, first.pos);
      }
    }
  }, [editor, stopCreating]);
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
    setHighlights({ pending: sel ? { from: sel.from, to: sel.to } : null });
    setSelectedId(null);
    setPanel("fields");
    setDrawer(true);
  }, [editor, setHighlights]);
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
    // o documento pode ter mudado desde a seleção: usa a posição do realce (mapeada) ou a seleção atual se ainda for o mesmo texto
    const pending = highlightKey.getState(editor.state)?.pending;
    if (range && pending && editor.state.doc.textBetween(pending.from, pending.to, "\n", "￼") === range.text) ({ from, to } = pending);
    if (range && editor.state.doc.textBetween(from, to, "\n", "￼") !== range.text) {
      const cur = selectionForField(editor);
      if (cur && cur.text === range.text) ({ from, to } = cur);
      else {
        from = to = editor.state.selection.from;
        sample = "";
      }
    }
    const marks = (editor.state.doc.nodeAt(from)?.marks ?? []).map((m) => ({ type: m.type.name }));
    editor.chain().focus().insertContentAt({ from, to }, { type: "field", attrs: { fieldId: f.id, sample }, marks }).run();
    setCounts(countFieldNodes(editor.state.doc));
  }

  function onCreated(f: FieldOut) {
    if (creating) insertChip(f, creating.text ? { from: creating.from, to: creating.to, text: creating.text } : undefined);
    syncOrder([...fields, f]);
    stopCreating();
    setSelectedId(f.id);
    toast.push({ tone: "success", title: `Campo “${f.label}” criado`, description: f.type === "select" ? undefined : "Ajuste os detalhes aqui ou selecione o próximo trecho no documento." });
  }

  function linkExisting(f: FieldOut) {
    if (!creating) return;
    insertChip(f, creating.text ? { from: creating.from, to: creating.to, text: creating.text } : undefined);
    syncOrder(fields);
    stopCreating();
    setSelectedId(f.id);
    toast.push({ tone: "success", title: `Trecho ligado ao campo “${f.label}”`, description: "Os dois trechos vão receber o mesmo valor." });
  }

  function insertExisting(f: FieldOut) {
    insertChip(f);
    syncOrder(fields);
    toast.push({ tone: "info", title: `“${f.label}” inserido onde estava o cursor` });
  }

  // ---- recarregar do servidor (após excluir campo / aceitar sugestões / restaurar versão)
  const reloadFromServer = useCallback(async () => {
    const p = await api.get<EditorPayload>(`/generators/${id}/editor`);
    editor?.commands.setContent(p.doc as JSONContent, { emitUpdate: false });
    autosave.reset(p.version.revision);
    syncOrder(p.fields);
    setVersion(p.version);
    setGenerator(p.generator);
    if (editor) {
      setCounts(countFieldNodes(editor.state.doc));
      setOutline(buildOutline(editor.state.doc));
    }
  }, [id, editor, autosave, syncOrder]);

  async function confirmDelete(mode: "keep_text" | "remove_text") {
    if (!toDelete) return;
    try {
      if (!(await autosave.flush())) throw new Error("Não foi possível salvar as alterações pendentes do documento.");
      await api.delete(`/fields/${toDelete.id}?occurrences=${mode}`);
      setSelectedId(null);
      await reloadFromServer();
      toast.push({ tone: "success", title: `Campo “${toDelete.label}” excluído`, description: mode === "keep_text" ? "O texto original voltou para o documento." : "O trecho foi removido do documento." });
      setToDelete(null);
    } catch (e) {
      toast.push({ tone: "danger", title: "Não foi possível excluir", description: errorMessage(e) });
    }
  }

  function moveField(fid: string, dir: -1 | 1) {
    const i = fields.findIndex((f) => f.id === fid);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= fields.length) return;
    const next = [...fields];
    [next[i], next[j]] = [next[j], next[i]];
    autoOrder.current = false; // a pessoa personalizou a ordem
    void persistOrder(next, fields);
  }

  async function goTo(href: string) {
    if (!(await autosave.flush())) {
      if (!window.confirm("Há alterações no documento que não foram salvas. Sair mesmo assim?")) return;
    }
    router.push(href);
  }

  async function saveName() {
    const n = name.trim();
    if (!n || n === generator.name) return setName(generator.name);
    try {
      setGenerator(await api.patch<GeneratorOut>(`/generators/${id}`, { name: n }));
      toast.push({ tone: "success", title: "Nome do modelo salvo" });
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
    setHighlights({ ranges: occ ? occ.map((o) => rangeOfOffsets(editor, o.block_key, o.start, o.end)).filter((r): r is { from: number; to: number } => !!r) : [] });
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

  const ctxValue = useMemo(() => ({ fields: fieldMap, issues, selectedId, select: (fid: string) => selectField(fid) }), [fieldMap, issues, selectedId, selectField]);
  const pendingSuggestions = useQuery({ queryKey: ["suggestions", id], queryFn: () => api.get<{ items: unknown[] }>(`/generators/${id}/suggestions`), staleTime: 5000 });
  const nSuggestions = pendingSuggestions.data?.items.length ?? 0;
  // ao reabrir um modelo sem campos e com sugestões pendentes, elas são o próximo passo — abre direto nelas (uma vez).
  const [autoTabDone, setAutoTabDone] = useState(false);
  if (!autoTabDone && pendingSuggestions.isSuccess) {
    setAutoTabDone(true);
    if (nSuggestions > 0 && fields.length === 0 && !selectedId && !creating) setPanel("suggestions");
  }

  const nIssues = Object.keys(issues).length;
  const hrefs = stepHrefs(id);

  const SaveBadge = (() => {
    const s = autosave.state;
    const base = "flex items-center gap-1.5 text-sm";
    if (s === "saving" || fieldSave?.state === "saving") return <span className={cn(base, "text-muted")}><Loader2 className="h-4 w-4 animate-spin" aria-hidden />Salvando…</span>;
    if (s === "conflict") return <span className={cn(base, "text-danger")}><AlertTriangle className="h-4 w-4" aria-hidden />Alterado em outra aba<button type="button" className="ml-1 underline" onClick={() => location.reload()}>Recarregar</button></span>;
    if (s === "error") return <span className={cn(base, "text-danger")} title={autosave.message ?? undefined}><AlertTriangle className="h-4 w-4" aria-hidden />Não salvou<button type="button" className="ml-1 underline" onClick={autosave.retry}>Tentar de novo</button></span>;
    if (fieldSave?.state === "error") return <span className={cn(base, "text-danger")} title={fieldSave.message}><AlertTriangle className="h-4 w-4" aria-hidden />Campo não salvo — veja o painel</span>;
    if (s === "dirty") return <span className={cn(base, "text-muted")}><span className="h-2 w-2 rounded-full bg-warning" aria-hidden />Alterações pendentes</span>;
    return <span className={cn(base, "text-success")}><Check className="h-4 w-4" aria-hidden />Tudo salvo</span>;
  })();

  const nextButton = (
    <Button variant="primary" size="sm" onClick={() => goTo(hrefs.review)} disabled={fields.length === 0} title={fields.length === 0 ? "Crie pelo menos um campo para revisar" : undefined} data-testid="go-review">
      <span className="hidden sm:inline">Próximo:</span> Revisão <ArrowRight className="h-4 w-4" aria-hidden />
    </Button>
  );

  return (
    <FieldsContext.Provider value={ctxValue}>
      <div className="flex h-dvh flex-col bg-bg">
        <header className="border-b border-border bg-surface">
          <div className="flex flex-wrap items-center gap-2 px-3 py-2">
            <Button variant="ghost" size="icon" aria-label="Voltar aos modelos" onClick={() => goTo("/models")}>
              <ArrowLeft className="h-4 w-4" aria-hidden />
            </Button>
            <div className="min-w-0 flex-1 sm:max-w-md">
              <label htmlFor="gen-name" className="sr-only">Nome do modelo</label>
              <Input id="gen-name" value={name} onChange={(e) => setName(e.target.value)} onBlur={saveName} onKeyDown={(e) => e.key === "Enter" && (e.currentTarget as HTMLInputElement).blur()} className="h-9 border-transparent bg-transparent font-semibold hover:border-border-strong" title="Clique para renomear" />
            </div>
            <div aria-live="polite" role="status" data-testid="save-state" data-state={autosave.state === "saved" && fieldSave?.state === "saving" ? "saving" : autosave.state} className="min-w-32">{SaveBadge}</div>
            <div className="ml-auto flex items-center gap-1">
              <Button variant="ghost" size="icon" aria-label="Desfazer" title="Desfazer (Ctrl+Z)" disabled={!editorState?.canUndo} onClick={() => editor?.chain().focus().undo().run()}>
                <Undo2 className="h-4 w-4" aria-hidden />
              </Button>
              <Button variant="ghost" size="icon" aria-label="Refazer" title="Refazer (Ctrl+Shift+Z)" disabled={!editorState?.canRedo} onClick={() => editor?.chain().focus().redo().run()}>
                <Redo2 className="h-4 w-4" aria-hidden />
              </Button>
              <Button variant="ghost" className="hidden lg:inline-flex" aria-pressed={navOpen} onClick={() => setNavOpen((o) => !o)} title="Buscar um trecho ou pular para títulos e tabelas">
                <Search className="h-4 w-4" aria-hidden /> <span className="hidden xl:inline">Buscar</span>
              </Button>
              <Button variant="ghost" onClick={() => setVersionsOpen(true)} title="Histórico de versões do documento" aria-label="Versões">
                <History className="h-4 w-4" aria-hidden /> <span className="hidden xl:inline">Versões</span>
              </Button>
              <Button className="lg:hidden" size="sm" onClick={() => setDrawer((d) => !d)} aria-expanded={drawer} aria-controls="fields-panel">
                <ListChecks className="h-4 w-4" aria-hidden /> Campos ({fields.length})
              </Button>
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-3 py-1.5">
            <GeneratorSteps id={id} current="fields" hasTemplate fieldsCount={fields.length} onNavigate={goTo} compact />
            {nextButton}
          </div>
        </header>

        <div className="relative flex min-h-0 flex-1">
          {navOpen && (
            <div className="hidden lg:flex">
              <DocNavigator onClose={() => setNavOpen(false)} outline={outline} onGoOutline={goOutline} search={search} onSearch={setSearch} matches={matchTotal} matchIndex={matchIdx} onMatchNav={navMatch} />
            </div>
          )}

          <main id="main" className="doc-canvas min-w-0 flex-1 overflow-y-auto px-3 py-6 sm:px-4" aria-label="Documento" tabIndex={-1}>
            <div className="mx-auto mb-4 max-w-[794px] space-y-3">
              {fields.length === 0 ? (
                <Alert tone="primary" title="Marque o que muda de um documento para outro">
                  Selecione no texto abaixo um trecho como um nome, CPF ou valor e clique em <strong>Transformar em campo</strong>.
                  {nSuggestions > 0 && <> Ou <button type="button" className="font-medium text-primary underline" onClick={() => { setPanel("suggestions"); setDrawer(true); }}>veja as {nSuggestions} sugestões</button> que encontramos.</>}
                </Alert>
              ) : (
                <p className="text-center text-xs text-muted">
                  Selecione um trecho e use <strong className="text-fg">Transformar em campo</strong> (ou <kbd className="rounded border border-border bg-surface px-1">Ctrl</kbd>+<kbd className="rounded border border-border bg-surface px-1">Shift</kbd>+<kbd className="rounded border border-border bg-surface px-1">F</kbd>). Clique num campo para configurá-lo.
                </p>
              )}
              {initial.warnings.length > 0 && <Alert tone="neutral">{initial.warnings.join(" ")}</Alert>}
            </div>
            <div className="doc-page" data-testid="doc-page">
              <EditorContent editor={editor} />
            </div>
            <p className="mx-auto mt-4 max-w-[794px] text-center text-xs text-muted">Visual contínuo: a paginação real aparece no Word/PDF gerado.</p>
          </main>

          <aside
            id="fields-panel"
            aria-label="Campos e sugestões"
            className={cn(
              "z-40 flex w-[min(26rem,100vw)] shrink-0 flex-col border-l border-border bg-surface",
              "fixed inset-y-0 right-0 transition-transform lg:static lg:translate-x-0",
              drawer ? "translate-x-0" : "translate-x-full",
            )}
          >
            <div className="flex items-center justify-end border-b border-border px-2 py-1 lg:hidden">
              <Button size="sm" variant="ghost" onClick={() => setDrawer(false)}><X className="h-4 w-4" aria-hidden /> Fechar painel</Button>
            </div>
            <Tabs
              value={panel}
              onValueChange={(v) => { setPanel(v); if (v === "suggestions") stopCreating(); }}
              className="flex min-h-0 flex-1 flex-col"
              tabs={[
                { value: "fields", label: <span className="inline-flex items-center gap-1">Campos ({fields.length}){nIssues > 0 && <AlertTriangle className="h-3.5 w-3.5 text-warning" aria-label={`${nIssues} com pendência`} />}</span> },
                { value: "suggestions", label: <span className="inline-flex items-center gap-1"><Sparkles className="h-3.5 w-3.5" aria-hidden />Sugestões{nSuggestions ? ` (${nSuggestions})` : ""}</span> },
              ]}
            >
              <TabPanel value="fields" className="min-h-0 flex-1 overflow-y-auto p-4">
                {creating ? (
                  <>
                    <div className="mb-3 flex items-center justify-between gap-2">
                      <h2 className="text-base font-semibold">Novo campo</h2>
                      <Button size="sm" variant="ghost" onClick={stopCreating}>Cancelar</Button>
                    </div>
                    <FieldForm
                      key={`new-${creating.from}-${creating.to}`}
                      mode="create" generatorId={id} siblings={fieldsView}
                      seed={{ label: creating.label, type: creating.type, example: creating.text, text: creating.text || undefined }}
                      onCreated={onCreated} onUseExisting={linkExisting} onCancel={stopCreating}
                    />
                  </>
                ) : selectedField ? (
                  <>
                    <Button size="sm" variant="ghost" className="-ml-2 mb-2" onClick={() => setSelectedId(null)} data-testid="back-to-list">
                      <ArrowLeft className="h-4 w-4" aria-hidden /> Todos os campos
                    </Button>
                    <h2 className="mb-3 break-words text-base font-semibold">Configurar “{selectedField.label}”</h2>
                    <FieldForm
                      key={selectedField.id} mode="edit" generatorId={id} field={selectedField} siblings={fieldsView} issues={issues[selectedField.id]}
                      occurrenceNav={{ count: selectedField.occurrences, onPrev: () => navOccurrence(selectedField.id, -1), onNext: () => navOccurrence(selectedField.id, 1) }}
                      onChanged={(f) => setFields((fs) => fs.map((x) => (x.id === f.id ? { ...x, ...f } : x)))}
                      onSaveState={setFieldSave}
                      onDelete={() => setToDelete(selectedField)}
                    />
                  </>
                ) : (
                  <>
                    <div className="mb-3 flex items-center justify-between gap-2">
                      <h2 className="text-base font-semibold">Campos do formulário</h2>
                      <Button size="sm" variant="ghost" onClick={() => startCreate(null)} title="Cria um campo e o insere onde está o cursor no documento">
                        <Plus className="h-4 w-4" aria-hidden /> No cursor
                      </Button>
                    </div>
                    <FieldList
                      fields={fieldsView} issues={issues} selectedId={selectedId} inDocOrder={inDocOrder} suggestions={nSuggestions}
                      onSelect={(f) => selectField(f.id, true)} onInsert={insertExisting} onMove={moveField} onSyncOrder={followDocumentOrder}
                      onShowSuggestions={() => setPanel("suggestions")}
                    />
                    {fields.length > 0 && (
                      <div className="mt-4 rounded-md border border-border bg-surface-2 p-3 text-sm" data-testid="next-step">
                        <p className="font-medium">Terminou de marcar os campos?</p>
                        <p className="mt-0.5 text-xs text-muted">Na revisão você vê o documento com dados de exemplo antes de gerar.</p>
                        <ButtonLink href={hrefs.review} onClick={(e) => { e.preventDefault(); void goTo(hrefs.review); }} variant="primary" size="sm" className="mt-2">
                          Revisar <ArrowRight className="h-4 w-4" aria-hidden />
                        </ButtonLink>
                      </div>
                    )}
                  </>
                )}
              </TabPanel>

              <TabPanel value="suggestions" className="min-h-0 flex-1 overflow-y-auto p-4">
                <SuggestionsPanel
                  generatorId={id} analysisStatus={initial.version.analysis_status}
                  beforeApply={autosave.flush}
                  onApplied={async () => reloadFromServer()}
                  onHighlight={highlightOccurrences} onLocate={locateOccurrence}
                  next={fields.length > 0 ? (
                    <div className="rounded-md border border-success/30 bg-success-soft p-3 text-sm">
                      <p className="font-medium">Nenhuma sugestão pendente.</p>
                      <Button size="sm" className="mt-2" onClick={() => setPanel("fields")}>Ver os {fields.length} campos</Button>
                    </div>
                  ) : null}
                />
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
    const noDoc = e.code === "NOT_FOUND" && /docx/i.test(e.message);
    return (
      <main id="main" className="mx-auto max-w-lg space-y-4 p-8">
        <Alert tone={noDoc ? "warning" : "danger"} title={noDoc ? "Falta enviar o documento" : e.code === "NOT_FOUND" ? "Modelo não encontrado" : "Não foi possível abrir o editor"}>
          {noDoc ? "Para criar campos, primeiro envie o documento deste modelo (Word .docx ou PDF digitado)." : errorMessage(e)}
        </Alert>
        <div className="flex flex-wrap gap-2">
          {noDoc && <ButtonLink href={stepHrefs(id).template} variant="primary">Enviar o documento</ButtonLink>}
          {!noDoc && e.code !== "NOT_FOUND" && <Button onClick={() => q.refetch()}>Tentar de novo</Button>}
          <ButtonLink href="/models">Voltar aos modelos</ButtonLink>
        </div>
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
