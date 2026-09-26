"use client";

import type { Editor } from "@tiptap/core";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";

export type SaveState = "saved" | "dirty" | "saving" | "error" | "conflict";

/**
 * Salvamento automático do documento com:
 *  - debounce (1,2 s), fila (uma requisição por vez; edições durante o envio geram novo envio);
 *  - controle de concorrência por `revision` (409 → estado "conflict");
 *  - retry com backoff em erro de rede; `flush()` para sair sem perder nada; aviso ao fechar a aba.
 */
export function useAutosave(editor: Editor | null, generatorId: string, initialRevision: number | null) {
  const [state, setState] = useState<SaveState>("saved");
  const [message, setMessage] = useState<string | null>(null);
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(null);
  const revision = useRef<number | null>(initialRevision);
  const dirty = useRef(false);
  const inflight = useRef<Promise<void> | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const failures = useRef(0);
  const blocked = useRef(false);
  const stateRef = useRef<SaveState>("saved");

  const set = useCallback((s: SaveState, msg: string | null = null) => {
    stateRef.current = s;
    setState(s);
    setMessage(msg);
  }, []);

  useEffect(() => {
    if (initialRevision !== null) revision.current = initialRevision;
  }, [initialRevision]);

  const run = useCallback(async (): Promise<void> => {
    if (!editor || blocked.current || revision.current === null) return;
    if (inflight.current) return inflight.current;
    if (!dirty.current) return;
    const p = (async () => {
      set("saving");
      dirty.current = false;
      try {
        const res = await api.put<{ revision: number }>(`/generators/${generatorId}/editor/content`, { revision: revision.current, doc: editor.getJSON() });
        revision.current = res.revision;
        failures.current = 0;
        setLastSavedAt(new Date());
        set(dirty.current ? "dirty" : "saved");
      } catch (e) {
        dirty.current = true;
        if (e instanceof ApiError && e.code === "STALE_REVISION") {
          blocked.current = true;
          set("conflict", e.message);
        } else if (e instanceof ApiError && e.status >= 400 && e.status < 500 && e.status !== 429) {
          blocked.current = true; // rejeição definitiva (ex.: estrutura inválida): não adianta repetir
          set("error", e.message);
        } else {
          failures.current += 1;
          set("error", e instanceof ApiError ? e.message : "Não foi possível salvar.");
          // eslint-disable-next-line react-hooks/immutability -- reagendamento recursivo: `run` já existe quando o timer dispara
          timer.current = setTimeout(() => void run(), Math.min(30_000, 2000 * 2 ** failures.current));
        }
      }
    })();
    inflight.current = p;
    await p;
    inflight.current = null;
    if (dirty.current && !blocked.current && stateRef.current !== "error") await run();
  }, [editor, generatorId, set]);

  const markDirty = useCallback(() => {
    if (blocked.current) return;
    dirty.current = true;
    if (stateRef.current !== "saving") set("dirty");
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => void run(), 1200);
  }, [run, set]);

  /** Envia agora tudo que estiver pendente (usado ao sair da página, publicar ou testar). */
  const flush = useCallback(async (): Promise<boolean> => {
    if (timer.current) clearTimeout(timer.current);
    if (inflight.current) await inflight.current;
    if (dirty.current && !blocked.current) await run();
    return !dirty.current && !blocked.current;
  }, [run]);

  /** Depois de recarregar o documento do servidor (ex.: excluir campo, aceitar sugestão). */
  const reset = useCallback((rev: number) => {
    revision.current = rev;
    dirty.current = false;
    blocked.current = false;
    failures.current = 0;
    if (timer.current) clearTimeout(timer.current);
    set("saved");
  }, [set]);

  const retry = useCallback(() => {
    if (blocked.current) return;
    failures.current = 0;
    void run();
  }, [run]);

  useEffect(() => {
    const onUnload = (e: BeforeUnloadEvent) => {
      if (dirty.current || inflight.current || stateRef.current === "error") {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", onUnload);
    return () => window.removeEventListener("beforeunload", onUnload);
  }, []);
  useEffect(() => () => void (timer.current && clearTimeout(timer.current)), []);

  return { state, message, lastSavedAt, markDirty, flush, reset, retry, getRevision: () => revision.current };
}
