"use client";

import { ArrowRight, CheckCircle2, FileUp, Loader2, LockKeyhole, RotateCcw, Sparkles, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { DocPreview } from "@/components/form/doc-preview";
import { ApiError, api, errorMessage } from "@/lib/api";
import type { TrialConfig, TrialStatus } from "@/lib/trial";
import { cn } from "@/lib/utils";

/*
 * "Teste com o seu documento" (D38): o visitante envia o .docx/PDF dele, sem conta, e vê os campos marcados.
 * A análise roda no servidor (fila), com limites por IP, teto de custo de IA e apagamento em 1 hora. O resultado
 * vira modelo da conta em /register?trial=<token> (ou /login?trial=…).
 */

type Phase = "idle" | "sending" | "processing" | "done" | "failed";

const TYPE_LABEL: Record<string, string> = {
  text_short: "Texto",
  text_long: "Texto longo",
  number: "Número",
  currency: "Valor",
  date: "Data",
  cpf: "CPF",
  cnpj: "CNPJ",
  cep: "CEP",
  email: "E-mail",
  phone: "Telefone",
  oab: "OAB",
  select: "Lista",
  yes_no: "Sim/Não",
  checkbox: "Caixa de marcar",
};

const POLL_MS = 1500;
const POLL_LIMIT_MS = 3 * 60 * 1000;

type TurnstileApi = {
  render: (el: HTMLElement, opts: Record<string, unknown>) => string;
  reset: (id?: string) => void;
  remove: (id?: string) => void;
};
declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

function loadTurnstile(): Promise<TurnstileApi> {
  return new Promise((resolve, reject) => {
    if (window.turnstile) return resolve(window.turnstile);
    const existing = document.getElementById("cf-turnstile-script") as HTMLScriptElement | null;
    const script = existing ?? document.createElement("script");
    script.addEventListener("load", () => (window.turnstile ? resolve(window.turnstile) : reject(new Error("turnstile"))));
    script.addEventListener("error", () => reject(new Error("turnstile")));
    if (!existing) {
      script.id = "cf-turnstile-script";
      script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
      script.async = true;
      document.head.appendChild(script);
    }
  });
}

export function TrialUpload() {
  const [config, setConfig] = useState<TrialConfig | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [status, setStatus] = useState<TrialStatus | null>(null);
  const [captcha, setCaptcha] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const pendingFile = useRef<File | null>(null); // escolhido antes de a verificação terminar
  const [waiting, setWaiting] = useState(false);
  const honeypot = useRef<HTMLInputElement>(null);
  const widgetEl = useRef<HTMLDivElement>(null);
  const widgetId = useRef<string | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    api
      .get<TrialConfig>("/public/trials/config")
      .then((c) => alive.current && setConfig(c))
      .catch(() => alive.current && setConfig(null));
    return () => {
      alive.current = false;
    };
  }, []);

  const poll = useCallback(async (t: string) => {
    const started = Date.now();
    while (alive.current && Date.now() - started < POLL_LIMIT_MS) {
      try {
        const s = await api.get<TrialStatus>(`/public/trials/${encodeURIComponent(t)}`);
        if (!alive.current) return;
        if (s.status === "done") {
          setStatus(s);
          setPhase("done");
          return;
        }
        if (s.status === "failed") {
          setError(s.error?.message ?? "Não foi possível ler este documento.");
          setPhase("failed");
          return;
        }
      } catch (e) {
        if (e instanceof ApiError && e.status !== 429) {
          setError(errorMessage(e));
          setPhase("failed");
          return;
        }
      }
      await new Promise((r) => setTimeout(r, POLL_MS));
    }
    if (alive.current) {
      setError("A análise está demorando mais que o normal. Tente de novo em instantes.");
      setPhase("failed");
    }
  }, []);

  const send = useCallback(
    async (file: File, challenge: string | null) => {
      setPhase("sending");
      setError(null);
      const fd = new FormData();
      fd.append("file", file);
      if (challenge) fd.append("turnstile_token", challenge);
      fd.append("website", honeypot.current?.value ?? "");
      try {
        const r = await api.post<{ token: string }>("/public/trials", fd);
        if (!alive.current) return;
        setToken(r.token);
        setPhase("processing");
        void poll(r.token);
      } catch (e) {
        setError(errorMessage(e));
        setPhase("failed");
      }
    },
    [poll],
  );

  const siteKey = config?.turnstile_site_key ?? null;
  useEffect(() => {
    if (!siteKey || phase !== "idle" || !widgetEl.current) return;
    let cancelled = false;
    loadTurnstile()
      .then((ts) => {
        if (cancelled || !widgetEl.current || widgetId.current) return;
        widgetId.current = ts.render(widgetEl.current, {
          sitekey: siteKey,
          action: "trial",
          language: "pt-br",
          callback: (t: string) => {
            setCaptcha(t);
            const f = pendingFile.current;
            if (f) {
              pendingFile.current = null;
              setWaiting(false);
              void send(f, t);
            }
          },
          "expired-callback": () => setCaptcha(null),
          "error-callback": () => setCaptcha(null),
        });
      })
      .catch(() => setError("Não foi possível carregar a verificação. Recarregue a página e tente de novo."));
    return () => {
      cancelled = true;
      if (widgetId.current && window.turnstile) window.turnstile.remove(widgetId.current);
      widgetId.current = null;
    };
  }, [siteKey, phase, send]);

  function pick(file: File | undefined) {
    if (!file || !config) return;
    setError(null);
    const lower = file.name.toLowerCase();
    const okType = lower.endsWith(".docx") || (config.accepts_pdf && lower.endsWith(".pdf"));
    if (!okType) {
      setError(config.accepts_pdf ? "Envie um arquivo .docx (Word) ou um PDF digitado." : "Envie um arquivo .docx (Word).");
      return;
    }
    if (file.size > config.max_mb * 1024 * 1024) {
      setError(`O teste aceita arquivos de até ${config.max_mb} MB.`);
      return;
    }
    setFileName(file.name);
    if (siteKey && !captcha) {
      pendingFile.current = file; // envia assim que a verificação terminar (callback do Turnstile)
      setWaiting(true);
      return;
    }
    void send(file, captcha);
  }

  function restart() {
    pendingFile.current = null;
    setWaiting(false);
    setPhase("idle");
    setError(null);
    setStatus(null);
    setToken(null);
    setFileName(null);
    setCaptcha(null);
  }

  function onDrop(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    setDragging(false);
    pick(e.dataTransfer.files?.[0]);
  }

  if (!config?.enabled) return null;
  const fields = status?.result?.fields ?? [];
  const labels = Object.fromEntries(fields.map((f) => [f.id, f.label]));
  const accept = config.accepts_pdf ? ".docx,.pdf" : ".docx";

  return (
    <div id="teste" data-testid="trial" className="scroll-mt-24 rounded-2xl border border-zinc-200 bg-white p-5 shadow-xl shadow-brand/5 sm:p-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-sm font-bold uppercase tracking-[0.18em] text-primary">Teste com o seu documento</p>
          <h3 className="mt-2 font-display text-2xl font-extrabold tracking-tight sm:text-3xl">Envie o seu contrato e veja os campos marcados.</h3>
          <p className="mt-2 max-w-2xl text-zinc-600">
            Sem cadastro. Word (.docx){config.accepts_pdf ? " ou PDF digitado" : ""}, até {config.max_mb} MB e {config.max_pages} páginas.
          </p>
        </div>
        {phase !== "idle" && (
          <button type="button" onClick={restart} className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-semibold text-zinc-600 ring-1 ring-zinc-200 hover:bg-zinc-50">
            <RotateCcw className="h-4 w-4" aria-hidden /> Testar outro
          </button>
        )}
      </div>

      <div aria-live="polite" className="mt-6">
        {phase === "idle" && (
          <>
            <label
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              className={cn(
                "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-5 py-10 text-center transition",
                "focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-primary",
                dragging ? "border-primary bg-primary-soft" : "border-zinc-300 bg-paper hover:border-primary/60",
              )}
            >
              <FileUp className="h-9 w-9 text-primary" aria-hidden />
              <span className="font-display text-lg font-bold text-ink">Arraste o arquivo aqui ou escolha no computador</span>
              <span className="rounded-full bg-highlight px-5 py-2 text-sm font-bold text-ink">Escolher arquivo</span>
              <input
                type="file"
                accept={accept}
                className="sr-only"
                data-testid="trial-file"
                aria-describedby="trial-privacy"
                onChange={(e) => {
                  pick(e.target.files?.[0]);
                  e.target.value = "";
                }}
              />
              {fileName && waiting && <span className="text-sm text-zinc-600">{fileName}: confirme a verificação abaixo para enviar.</span>}
            </label>
            {siteKey && <div ref={widgetEl} className="mt-4 flex justify-center" />}
            <div aria-hidden className="absolute -left-[9999px] h-px w-px overflow-hidden">
              <label>
                Seu site
                <input ref={honeypot} type="text" name="website" tabIndex={-1} autoComplete="off" defaultValue="" />
              </label>
            </div>
            <p id="trial-privacy" className="mt-4 flex items-start gap-2 text-sm text-zinc-500">
              <LockKeyhole className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              <span>
                O arquivo é apagado em 1 hora e não é usado para treinar IA. Não envie dados de outras pessoas sem autorização.{" "}
                <Link href="/privacidade" className="underline underline-offset-2 hover:text-zinc-800">
                  Privacidade
                </Link>
              </span>
            </p>
          </>
        )}

        {(phase === "sending" || phase === "processing") && (
          <div role="status" className="flex flex-col items-center gap-3 rounded-xl bg-paper px-5 py-12 text-center">
            <Loader2 className="h-8 w-8 animate-spin text-primary" aria-hidden />
            <p className="font-display text-lg font-bold">{phase === "sending" ? "Enviando o documento…" : "Procurando nomes, CPFs, valores e datas…"}</p>
            <p className="text-sm text-zinc-500">{fileName} · costuma levar menos de 30 segundos.</p>
          </div>
        )}

        {phase === "failed" && (
          <div role="alert" className="flex flex-col items-start gap-3 rounded-xl border border-red-200 bg-red-50 p-5 text-red-900">
            <p className="flex items-start gap-2 font-semibold">
              <TriangleAlert className="mt-0.5 h-5 w-5 shrink-0" aria-hidden /> {error}
            </p>
            <div className="flex flex-wrap gap-3">
              <button type="button" onClick={restart} className="rounded-full bg-white px-4 py-2 text-sm font-semibold text-ink ring-1 ring-red-200 hover:bg-red-100">
                Tentar outro arquivo
              </button>
              <Link href="/register" className="rounded-full bg-highlight px-4 py-2 text-sm font-bold text-ink">
                Criar conta grátis
              </Link>
            </div>
          </div>
        )}

        {phase === "idle" && error && (
          <p role="alert" className="mt-3 flex items-start gap-2 text-sm font-semibold text-red-700">
            <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden /> {error}
          </p>
        )}

        {phase === "done" && status?.result && token && (
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
            <div className="max-h-[22rem] overflow-auto rounded-xl bg-paper p-2 ring-1 ring-zinc-200 sm:max-h-[34rem] sm:p-4" tabIndex={0} aria-label="Documento com os campos destacados">
              <DocPreview doc={status.result.doc} fields={[]} values={{}} found={labels} />
            </div>
            <div className="flex min-w-0 flex-col">
              <p className="flex items-center gap-2 font-display text-xl font-extrabold" data-testid="trial-count">
                <CheckCircle2 className="h-6 w-6 text-brand" aria-hidden />
                {fields.length === 1 ? "1 campo encontrado" : `${fields.length} campos encontrados`}
              </p>
              <p className="mt-1 text-sm text-zinc-500">
                {status.ai === "ai" ? (
                  <span className="inline-flex items-center gap-1">
                    <Sparkles className="h-4 w-4 text-primary" aria-hidden /> Encontrados pela IA. Na sua conta, você confere e ajusta cada um.
                  </span>
                ) : status.ai === "budget" ? (
                  "A IA do teste chegou ao limite de hoje. Mostramos os campos achados pelas regras automáticas; na sua conta, a IA está disponível."
                ) : (
                  "Encontrados pelas regras automáticas. Na sua conta, você confere e ajusta cada um."
                )}
              </p>
              {fields.length > 0 ? (
                <ul className="mt-4 max-h-80 space-y-2 overflow-auto pr-1" data-testid="trial-fields">
                  {fields.map((f) => (
                    <li key={f.id} className="rounded-lg border border-zinc-200 bg-white px-3 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate font-semibold text-ink">{f.label}</span>
                        <span className="shrink-0 rounded-full bg-zinc-100 px-2 py-0.5 text-xs font-medium text-zinc-600">{TYPE_LABEL[f.type] ?? "Texto"}</span>
                      </div>
                      <p className="mt-0.5 truncate text-sm text-zinc-500">
                        <mark className="rounded bg-highlight-soft px-1 text-ink">{f.sample}</mark>
                        {f.count > 1 && <span> · aparece {f.count} vezes</span>}
                      </p>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-4 text-zinc-600">Não achamos campos automaticamente neste documento. Na sua conta, você marca cada trecho com um clique.</p>
              )}
              {status.result.warnings.map((w) => (
                <p key={w} className="mt-3 text-sm text-zinc-500">
                  {w}
                </p>
              ))}
              <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:flex-wrap lg:flex-col">
                <Link
                  href={`/register?trial=${encodeURIComponent(token)}`}
                  data-testid="trial-save"
                  className="group inline-flex items-center justify-center gap-2 rounded-full bg-highlight px-6 py-3 text-base font-bold text-ink shadow-lg shadow-highlight/20 transition hover:bg-[#ffe066]"
                >
                  Criar conta grátis e salvar este modelo
                  <ArrowRight className="h-4 w-4 transition group-hover:translate-x-0.5" aria-hidden />
                </Link>
                <Link href={`/login?trial=${encodeURIComponent(token)}`} className="text-center text-sm font-semibold text-primary underline underline-offset-2">
                  Já tenho conta: entrar e salvar
                </Link>
              </div>
              <p className="mt-3 text-xs text-zinc-500">Este resultado fica disponível por 1 hora.</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
