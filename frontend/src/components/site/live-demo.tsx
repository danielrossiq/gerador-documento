"use client";

import { Check, FileDown, Loader2, RotateCcw, Sparkles, Wand2 } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DEMO_DOCS, initialValues, type DemoDoc, type DemoField, type Segment } from "@/components/site/demo-data";
import { currencyWords } from "@/lib/fields/extenso";
import { liveMask } from "@/lib/fields/masks";
import { isValidCpf, parseDecimal } from "@/lib/fields/normalize";
import { cn } from "@/lib/utils";

/*
 * Demonstração do produto na landing (sem backend, sem custo): o documento "original", a IA marcando os campos,
 * o formulário gerado e o documento mudando ao vivo. Formatação (máscara de CPF, valor por extenso) usa as mesmas
 * funções do produto. Modo "auto" se usa sozinho (topo da página); "interactive" é operado pelo visitante.
 */

type Phase = "raw" | "scan" | "marked" | "form" | "generating" | "done";

const MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];

function dateText(v: string): string {
  const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(v);
  if (!m) return v;
  const day = Number(m[1]);
  const month = MONTHS[Number(m[2]) - 1];
  return month ? `${day === 1 ? "1º" : day} de ${month} de ${m[3]}` : v;
}

function display(field: DemoField, raw: string, words?: boolean): string {
  if (!raw.trim()) return `[${field.label}]`;
  if (field.type === "currency") {
    if (words) return currencyWords(parseDecimal(raw) ?? "") ?? "…";
    return `R$ ${raw}`;
  }
  if (field.type === "date" && words) return dateText(raw);
  return raw;
}

function maskInput(field: DemoField, text: string): string {
  if (field.type === "cpf" || field.type === "date") return liveMask(field.type, text);
  if (field.type === "number") return text.replace(/\D/g, "").slice(0, 3);
  if (field.type === "currency") {
    const d = text.replace(/\D/g, "").replace(/^0+/, "").slice(0, 11);
    if (!d) return "";
    const cents = d.padStart(3, "0");
    const int = cents.slice(0, -2).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    return `${int},${cents.slice(-2)}`;
  }
  return text;
}

function fieldError(field: DemoField, v: string): string | null {
  if (field.type === "cpf" && v.replace(/\D/g, "").length === 11 && !isValidCpf(v)) return "CPF inválido";
  return null;
}

const prefersReducedMotion = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

function useTimeline() {
  const timers = useRef<number[]>([]);
  const clear = useCallback(() => {
    timers.current.forEach((t) => window.clearTimeout(t));
    timers.current = [];
  }, []);
  const at = useCallback((ms: number, fn: () => void) => {
    timers.current.push(window.setTimeout(fn, ms));
  }, []);
  useEffect(() => clear, [clear]);
  return { at, clear };
}

function DocPage({ doc, values, phase, revealed, focused, compact }: {
  doc: DemoDoc;
  values: Record<string, string>;
  phase: Phase;
  revealed: number;
  focused: string | null;
  compact?: boolean;
}) {
  const order = useMemo(() => doc.fields.map((f) => f.key), [doc]);
  const byKey = useMemo(() => Object.fromEntries(doc.fields.map((f) => [f.key, f])), [doc]);
  const marked = phase !== "raw" && phase !== "scan";

  const seg = (s: Segment, i: number) => {
    if (typeof s === "string") return <span key={i}>{s}</span>;
    const field = byKey[s.f];
    const value = values[s.f] ?? "";
    const show = marked && order.indexOf(s.f) < revealed;
    const edited = value !== field.example;
    return (
      <span
        key={i}
        data-field={s.f}
        title={show ? field.label : undefined}
        className={cn(
          "rounded-[3px] transition-all duration-300",
          show && "px-0.5 ring-1",
          show && !edited && "bg-highlight-soft text-ink ring-highlight",
          show && edited && "bg-primary-soft text-ink ring-brand",
          show && focused === s.f && "ring-2 ring-primary shadow-[0_0_0_4px_rgb(18_184_134_/_0.18)]",
        )}
      >
        {display(field, value, s.as === "words")}
      </span>
    );
  };

  return (
    <div className={cn("relative h-full overflow-hidden rounded-md bg-white shadow-[0_1px_3px_rgb(16_24_40_/_0.12),0_10px_30px_rgb(16_24_40_/_0.10)]", compact ? "px-5 py-6" : "px-6 py-8 sm:px-10 sm:py-10")}>
      {phase === "scan" && <div aria-hidden className="site-scan pointer-events-none absolute inset-x-0 top-0 z-10 h-24" />}
      <article className={cn("font-serif text-zinc-800", compact ? "text-[11px] leading-[1.7]" : "text-[13px] leading-[1.8] sm:text-[14px]")}>
        <h3 className={cn("mb-4 text-center font-bold tracking-wide text-zinc-900", compact ? "text-[11.5px]" : "text-[14px] sm:text-[15px]")}>{doc.title}</h3>
        {doc.body.map((p, pi) => (
          <p key={pi} className="mb-3 text-justify">
            {p.map(seg)}
          </p>
        ))}
        {doc.signature && (
          <div className={cn("mt-6 text-center", compact && "mt-4")}>
            <div className="mx-auto mb-1 h-px w-48 bg-zinc-400" />
            <p>{doc.signature.map(seg)}</p>
          </div>
        )}
      </article>
    </div>
  );
}

export function LiveDemo({ mode, compact }: { mode: "auto" | "interactive"; compact?: boolean }) {
  const [docIdx, setDocIdx] = useState(0);
  const doc = DEMO_DOCS[docIdx];
  const [values, setValues] = useState<Record<string, string>>(() => initialValues(DEMO_DOCS[0]));
  const [phase, setPhase] = useState<Phase>("raw");
  const [revealed, setRevealed] = useState(0);
  const [focused, setFocused] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState<number | null>(null);
  const { at, clear } = useTimeline();
  const total = doc.fields.length;

  const reset = useCallback((i: number) => {
    clear();
    setDocIdx(i);
    setValues(initialValues(DEMO_DOCS[i]));
    setRevealed(0);
    setFocused(null);
    setElapsed(null);
    setPhase("raw");
  }, [clear]);

  const analyse = useCallback((after?: () => void) => {
    clear();
    setPhase("scan");
    at(1300, () => {
      setPhase("marked");
      const n = DEMO_DOCS[docIdx].fields.length;
      for (let k = 1; k <= n; k++) at(k * 130, () => setRevealed(k));
      at(n * 130 + 500, () => {
        setPhase("form");
        after?.();
      });
    });
  }, [at, clear, docIdx]);

  const generate = useCallback(() => {
    const started = performance.now();
    setPhase("generating");
    at(900, () => {
      setElapsed(Math.max(0.6, Math.round((performance.now() - started) / 100) / 10));
      setPhase("done");
    });
  }, [at]);

  // ------------------------------------------------------------------ modo automático (topo da página)
  useEffect(() => {
    if (mode !== "auto") return;
    clear();
    if (prefersReducedMotion()) {
      // sem animação: mostra direto o resultado (campos marcados e formulário)
      at(0, () => {
        setRevealed(total);
        setPhase("form");
      });
      return clear;
    }
    const typeInto = (key: string, text: string, start: number) => {
      at(start, () => setFocused(key));
      for (let c = 0; c <= text.length; c++) at(start + 80 + c * 55, () => setValues((v) => ({ ...v, [key]: text.slice(0, c) })));
      return start + 80 + text.length * 55 + 350;
    };
    at(1100, () => setPhase("scan"));
    at(2400, () => setPhase("marked"));
    for (let k = 1; k <= total; k++) at(2400 + k * 120, () => setRevealed(k));
    let t = 2400 + total * 120 + 700;
    at(t, () => setPhase("form"));
    t += 500;
    const typed = doc.fields.filter((f) => f.alt).slice(0, 2);
    for (const f of typed) t = typeInto(f.key, f.type === "cpf" ? f.alt!.replace(/\D/g, "") : f.alt!, t);
    at(t, () => setFocused(null));
    t += 300;
    at(t, () => setPhase("generating"));
    at(t + 900, () => {
      setElapsed(0.8);
      setPhase("done");
    });
    at(t + 3600, () => {
      const next = (docIdx + 1) % DEMO_DOCS.length;
      setDocIdx(next);
      setValues(initialValues(DEMO_DOCS[next]));
      setRevealed(0);
      setElapsed(null);
      setPhase("raw");
    });
    return clear;
    // reinicia a sequência a cada documento
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, docIdx]);

  // a máscara do CPF digitado no modo automático
  const shownValues = useMemo(() => {
    const out: Record<string, string> = {};
    for (const f of doc.fields) out[f.key] = maskInput(f, values[f.key] ?? "");
    return out;
  }, [doc, values]);

  const formVisible = phase === "form" || phase === "generating" || phase === "done";
  const errors = doc.fields.map((f) => fieldError(f, shownValues[f.key])).filter(Boolean).length;

  return (
    <div className={cn("overflow-hidden rounded-xl border border-white/10 bg-zinc-100 shadow-2xl", compact ? "text-[13px]" : "")} data-testid={mode === "auto" ? "hero-demo" : "live-demo"}>
      {/* barra da janela */}
      <div className="flex items-center gap-2 border-b border-zinc-200 bg-white px-3 py-2">
        <span className="flex gap-1.5" aria-hidden>
          <span className="h-2.5 w-2.5 rounded-full bg-red-400" />
          <span className="h-2.5 w-2.5 rounded-full bg-amber-400" />
          <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
        </span>
        {mode === "interactive" ? (
          <div role="tablist" aria-label="Documento de exemplo" className="ml-2 flex min-w-0 gap-1 overflow-x-auto">
            {DEMO_DOCS.map((d, i) => (
              <button
                key={d.id}
                role="tab"
                aria-selected={i === docIdx}
                onClick={() => reset(i)}
                className={cn("whitespace-nowrap rounded-md px-2.5 py-1 text-xs font-medium transition", i === docIdx ? "bg-ink text-white" : "text-zinc-600 hover:bg-zinc-100")}
              >
                {d.tab}
              </button>
            ))}
          </div>
        ) : (
          <span className="ml-2 truncate text-xs font-medium text-zinc-500">DocFeito · {doc.tab}</span>
        )}
        <span className="ml-auto hidden items-center gap-1 rounded-full bg-primary-soft px-2 py-0.5 text-[11px] font-semibold text-primary sm:flex">
          <Sparkles className="h-3 w-3" aria-hidden /> IA
        </span>
      </div>

      <div className={cn("grid", compact ? "md:grid-cols-[1.35fr_1fr]" : "lg:grid-cols-[1.5fr_1fr]")}>
        {/* documento */}
        <div className={cn("relative bg-zinc-100", compact ? "p-3 sm:p-4" : "p-4 sm:p-6")}>
          <DocPage doc={doc} values={shownValues} phase={phase} revealed={revealed} focused={focused} compact={compact} />
          {mode === "interactive" && phase === "raw" && (
            <div className="absolute inset-0 grid place-items-center bg-zinc-900/10 backdrop-blur-[1px]">
              <button
                onClick={() => analyse()}
                className="site-pulse flex items-center gap-2 rounded-full bg-primary px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-brand/20 transition hover:bg-primary-hover"
                data-testid="demo-analyse"
              >
                <Wand2 className="h-4 w-4" aria-hidden /> Encontrar os campos com IA
              </button>
            </div>
          )}
          <div aria-live="polite" className="sr-only">
            {phase === "scan" ? "Analisando o documento" : phase === "form" ? `${total} campos encontrados` : phase === "done" ? "Documento gerado" : ""}
          </div>
        </div>

        {/* painel lateral */}
        <div className={cn("border-t border-zinc-200 bg-white lg:border-l lg:border-t-0", compact ? "p-3 md:border-l md:border-t-0" : "p-4 sm:p-5")}>
          {!formVisible ? (
            <div className="flex h-full min-h-40 flex-col justify-center gap-3 text-zinc-500">
              {phase === "raw" && (
                <>
                  <p className="text-sm font-semibold text-zinc-800">Seu documento, do jeito que está.</p>
                  <p className="text-xs">Word ou PDF que você já usa. Nada de montar formulário na mão.</p>
                </>
              )}
              {(phase === "scan" || phase === "marked") && (
                <div className="space-y-2" aria-hidden>
                  <p className="flex items-center gap-2 text-sm font-semibold text-primary">
                    <Loader2 className="h-4 w-4 animate-spin" /> A IA está lendo o documento…
                  </p>
                  <p className="text-xs">{revealed > 0 ? `${revealed} de ${total} campos encontrados` : "Procurando nomes, CPFs, valores e datas"}</p>
                  <div className="h-1.5 overflow-hidden rounded-full bg-zinc-100">
                    <div className="h-full rounded-full bg-brand transition-all duration-300" style={{ width: `${(revealed / total) * 100}%` }} />
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="flex h-full flex-col">
              <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-primary">
                <Check className="h-3.5 w-3.5" aria-hidden /> {total} campos encontrados · formulário pronto
              </p>
              <div className={cn("grid gap-2", compact ? "grid-cols-1" : "grid-cols-1 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2")}>
                {(compact ? doc.fields.slice(0, 4) : doc.fields).map((f) => {
                  const err = fieldError(f, shownValues[f.key]);
                  return (
                    <label key={f.key} className="block">
                      <span className="mb-0.5 block text-[11px] font-medium text-zinc-500">{f.label}</span>
                      <input
                        value={shownValues[f.key]}
                        readOnly={mode === "auto"}
                        tabIndex={mode === "auto" ? -1 : undefined}
                        inputMode={f.type === "text" ? "text" : "numeric"}
                        onFocus={() => setFocused(f.key)}
                        onBlur={() => setFocused(null)}
                        onChange={(e) => setValues((v) => ({ ...v, [f.key]: maskInput(f, e.target.value) }))}
                        aria-invalid={!!err}
                        className={cn(
                          "h-8 w-full rounded-md border bg-white px-2 text-[13px] text-zinc-900 outline-none transition",
                          focused === f.key ? "border-primary ring-2 ring-primary/20" : "border-zinc-300",
                          err && "border-red-500",
                        )}
                      />
                      {err && <span className="text-[11px] font-medium text-red-600">{err}</span>}
                    </label>
                  );
                })}
              </div>
              <div className="mt-auto pt-3">
                {phase === "done" ? (
                  <div className="rounded-lg border border-brand/30 bg-primary-soft p-3" data-testid="demo-done">
                    <p className="flex items-center gap-2 text-sm font-semibold text-primary">
                      <FileDown className="h-4 w-4" aria-hidden /> {doc.file(shownValues)}
                    </p>
                    <p className="mt-0.5 text-xs text-primary/80">Pronto em {String(elapsed ?? 0.8).replace(".", ",")} s. Agora imagine 500 de uma vez, a partir de uma planilha.</p>
                    {mode === "interactive" && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        <Link href="/register" className="rounded-md bg-highlight px-3 py-1.5 text-xs font-semibold text-ink hover:bg-[#ffe066]">
                          Fazer isso com os meus documentos
                        </Link>
                        <button onClick={() => reset(docIdx)} className="flex items-center gap-1 rounded-md px-2 py-1.5 text-xs font-medium text-zinc-600 hover:bg-zinc-100">
                          <RotateCcw className="h-3.5 w-3.5" aria-hidden /> Recomeçar
                        </button>
                      </div>
                    )}
                  </div>
                ) : (
                  <button
                    onClick={mode === "interactive" ? generate : undefined}
                    tabIndex={mode === "auto" ? -1 : undefined}
                    disabled={phase === "generating" || errors > 0}
                    className={cn(
                      "flex w-full items-center justify-center gap-2 rounded-md bg-primary py-2 text-sm font-semibold text-white transition hover:bg-primary-hover disabled:opacity-60",
                      phase === "generating" && "scale-[0.98]",
                    )}
                    data-testid="demo-generate"
                  >
                    {phase === "generating" ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <FileDown className="h-4 w-4" aria-hidden />}
                    {phase === "generating" ? "Gerando documento…" : "Gerar documento (PDF)"}
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
