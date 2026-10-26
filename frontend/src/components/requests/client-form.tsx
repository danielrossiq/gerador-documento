"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { CalendarClock, Camera, CheckCircle2, Loader2, LockKeyhole, Pencil, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";
import { LogoMark } from "@/components/brand/logo";
import { FieldInput } from "@/components/form/field-input";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/misc";
import { ApiError, api, errorMessage } from "@/lib/api";
import { normalizeValue, type FieldSpec } from "@/lib/fields/normalize";
import { shortDate, type PublicRequest } from "@/lib/requests";
import type { FieldOut } from "@/lib/types";

/*
 * Página do cliente no link (D39), pensada para o celular. Mostra só o nome de quem pediu, o documento, a mensagem e
 * os campos pedidos — tudo como texto (o React escapa; nada de HTML vindo do servidor). Mesmas máscaras e validações
 * do formulário do app; o servidor valida de novo.
 */

type Open = Extract<PublicRequest, { state: "open" | "answered" }>;
const spec = (f: FieldOut): FieldSpec => ({ name: f.name, label: f.label, type: f.type, required: f.required, default_value: null, options: f.options, config: f.config, mask: f.mask });

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main id="main" className="min-h-screen bg-bg px-4 py-6 sm:py-10">
      <div className="mx-auto w-full max-w-xl">{children}</div>
      <p className="mx-auto mt-8 flex max-w-xl items-center justify-center gap-1.5 text-xs text-muted">
        <LogoMark className="h-4 w-4" /> Enviado com segurança pelo DocFeito
      </p>
    </main>
  );
}

function Message({ icon, title, children }: { icon: React.ReactNode; title: string; children?: React.ReactNode }) {
  return (
    <Shell>
      <div className="rounded-xl border border-border bg-surface p-6 text-center shadow-sm" data-testid="request-message">
        <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-full bg-primary-soft text-primary">{icon}</div>
        <h1 className="font-display text-xl font-extrabold">{title}</h1>
        {children && <div className="mt-2 text-sm text-muted">{children}</div>}
      </div>
    </Shell>
  );
}

export function ClientForm({ token }: { token: string }) {
  const [data, setData] = useState<PublicRequest | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const path = `/public/requests/${encodeURIComponent(token)}`;

  useEffect(() => {
    let alive = true;
    api
      .get<PublicRequest>(path)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setLoadError(e instanceof ApiError && e.status === 404 ? "gone" : errorMessage(e)));
    return () => {
      alive = false;
    };
  }, [path]);

  if (loadError === "gone") {
    return (
      <Message icon={<LockKeyhole className="h-6 w-6" aria-hidden />} title="Este link não está mais disponível">
        Ele pode ter sido cancelado. Peça um novo a quem enviou.
      </Message>
    );
  }
  if (loadError) {
    return (
      <Message icon={<TriangleAlert className="h-6 w-6" aria-hidden />} title="Não foi possível abrir a página">
        {loadError}
      </Message>
    );
  }
  if (!data) {
    return (
      <Shell>
        <p role="status" className="flex items-center justify-center gap-2 py-20 text-muted">
          <Loader2 className="h-5 w-5 animate-spin" aria-hidden /> Carregando…
        </p>
      </Shell>
    );
  }
  if (data.state === "expired") {
    return (
      <Message icon={<CalendarClock className="h-6 w-6" aria-hidden />} title="Este link venceu">
        Peça um novo link a quem enviou.
      </Message>
    );
  }
  if (data.state === "closed") {
    return (
      <Message icon={<CheckCircle2 className="h-6 w-6" aria-hidden />} title="Seus dados já foram recebidos">
        Se precisar mudar alguma coisa, fale com quem enviou o link.
      </Message>
    );
  }
  if (sent) {
    return (
      <Message icon={<CheckCircle2 className="h-6 w-6" aria-hidden />} title="Pronto, recebemos seus dados!">
        <p>
          <strong className="text-fg">{data.workspace}</strong> vai conferir e preparar o documento. Você pode fechar esta página.
        </p>
        <button type="button" className="mt-4 inline-flex items-center gap-1.5 font-medium text-primary underline" onClick={() => setSent(false)} data-testid="request-edit-again">
          <Pencil className="h-4 w-4" aria-hidden /> Corrigir e enviar de novo
        </button>
      </Message>
    );
  }
  return <FillForm data={data} path={path} onSent={(d) => { setData(d); setSent(true); }} />;
}

function FillForm({ data, path, onSent }: { data: Open; path: string; onSent: (d: Open) => void }) {
  const fixed = useMemo<Record<string, unknown>>(() => (data.prefill_mode === "readonly" ? data.prefill : {}), [data]);
  const editable = useMemo(() => data.fields.filter((f) => !(f.name in fixed)), [data.fields, fixed]);
  const schema = useMemo(
    () =>
      z.object(
        Object.fromEntries(
          editable.map((f) => [
            f.name,
            z.any().superRefine((v, ctx) => {
              const { error } = normalizeValue(spec(f), v);
              if (error) ctx.addIssue({ code: "custom", message: error });
            }),
          ]),
        ),
      ),
    [editable],
  );
  const initial = useMemo(() => {
    const base = data.prefill_mode === "editable" ? data.prefill : {};
    const v: Record<string, unknown> = {};
    for (const f of editable) {
      const prev = data.values[f.name] ?? base[f.name];
      v[f.name] = f.type === "checkbox" ? prev === true : prev == null ? "" : String(prev);
    }
    return v;
  }, [data, editable]);
  const form = useForm<Record<string, unknown>>({ resolver: zodResolver(schema), defaultValues: initial, mode: "onBlur" });
  const errors = form.formState.errors;
  const [error, setError] = useState<string | null>(null);
  const [reading, setReading] = useState(false);
  const [readNote, setReadNote] = useState<string | null>(null);
  const [readsLeft, setReadsLeft] = useState(data.photos.reads_left);
  const fileRef = useRef<HTMLInputElement>(null);

  // handleSubmit (e não trigger): depois da 1ª tentativa, o erro some enquanto a pessoa corrige, e o botão não "pula"
  // no clique (sem isso, o blur do último campo tirava uma mensagem de erro e o clique caía fora do botão)
  async function send(values: Record<string, unknown>) {
    setError(null);
    try {
      await api.post(path, { values });
      onSent({ ...data, state: "answered", values: { ...fixed, ...values } });
    } catch (e) {
      if (e instanceof ApiError && e.code === "REQUEST_INVALID_VALUES") {
        const fe = (e.details as { field_errors?: Record<string, string> } | undefined)?.field_errors ?? {};
        Object.entries(fe).forEach(([name, message]) => form.setError(name, { message }));
      }
      setError(errorMessage(e));
    }
  }

  async function readPhotos(list: FileList | null) {
    if (!list?.length) return;
    const files = Array.from(list).slice(0, 3);
    const bad = files.find((f) => f.size > 8 * 1024 * 1024 || !/^(image\/(jpeg|png|webp)|application\/pdf)$/.test(f.type));
    if (bad) {
      setReadNote("Envie fotos (JPG, PNG ou WEBP) ou PDF de até 8 MB.");
      return;
    }
    setReading(true);
    setReadNote(null);
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    try {
      const r = await api.post<{ values: Record<string, string>; missing: string[]; reads_left: number }>(`${path}/fill-files`, fd);
      const found = Object.entries(r.values).filter(([name]) => editable.some((f) => f.name === name));
      for (const [name, v] of found) form.setValue(name, v, { shouldDirty: true });
      void form.trigger(found.map(([n]) => n));
      setReadsLeft(r.reads_left);
      setReadNote(found.length ? `Preenchemos ${found.length} ${found.length === 1 ? "campo" : "campos"}. Confira antes de enviar.` : "Não conseguimos ler os dados nesta foto. Tente outra mais nítida ou preencha à mão.");
    } catch (e) {
      setReadNote(errorMessage(e));
      if (e instanceof ApiError && e.code === "REQUEST_READS_USED") setReadsLeft(0);
    } finally {
      setReading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <Shell>
      <header className="mb-5">
        <p className="text-sm font-semibold text-primary" data-testid="request-workspace">{data.workspace}</p>
        <h1 className="mt-1 font-display text-2xl font-extrabold leading-tight tracking-tight">Preencha seus dados para: {data.document}</h1>
        {data.message && (
          <blockquote className="mt-3 whitespace-pre-line rounded-lg border-l-4 border-highlight bg-surface px-4 py-3 text-sm" data-testid="request-note">
            {data.message}
          </blockquote>
        )}
        <p className="mt-3 text-xs text-muted">Link válido até {shortDate(data.expires_at)}. Seus dados vão só para quem pediu.</p>
      </header>

      <form onSubmit={form.handleSubmit(send, () => setError("Confira os campos destacados."))} noValidate className="space-y-5 rounded-xl border border-border bg-surface p-4 shadow-sm sm:p-6" aria-label="Seus dados">
        {data.photos.allowed && readsLeft > 0 && (
          <div className="rounded-lg bg-primary-soft p-4">
            <p className="text-sm font-semibold text-fg">Tem o documento em mãos?</p>
            <p className="mt-0.5 text-xs text-muted">Tire uma foto do RG, CNH ou comprovante e a gente preenche para você conferir.</p>
            <label className="mt-3 inline-flex h-11 w-full cursor-pointer items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-primary-fg focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-primary sm:w-auto">
              {reading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Camera className="h-4 w-4" aria-hidden />}
              {reading ? "Lendo o documento…" : "Preencher com a foto do documento"}
              <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp,application/pdf" multiple className="sr-only" disabled={reading} onChange={(e) => void readPhotos(e.target.files)} data-testid="request-photo" />
            </label>
            {readNote && <p role="status" className="mt-2 text-sm">{readNote}</p>}
          </div>
        )}
        {data.photos.allowed && readsLeft === 0 && readNote && <Alert tone="warning">{readNote}</Alert>}

        {Object.keys(fixed).length > 0 && (
          <dl className="space-y-1 rounded-lg border border-border bg-surface-2 p-3 text-sm" aria-label="Dados já informados">
            {data.fields.filter((f) => f.name in fixed).map((f) => (
              <div key={f.name} className="flex flex-wrap gap-x-2">
                <dt className="text-muted">{f.label}:</dt>
                <dd className="font-medium">{String(fixed[f.name] ?? "")}</dd>
              </div>
            ))}
          </dl>
        )}

        {editable.map((f) => (
          <Controller
            key={f.name}
            name={f.name}
            control={form.control}
            render={({ field }) => (
              <FieldInput field={f} value={field.value} onChange={(v) => field.onChange(v)} onBlur={field.onBlur} error={(errors[f.name]?.message as string | undefined) ?? null} />
            )}
          />
        ))}

        {error && <Alert tone="danger">{error}</Alert>}
        <Button type="submit" variant="primary" size="lg" className="w-full justify-center" loading={form.formState.isSubmitting} data-testid="request-submit">
          Enviar meus dados
        </Button>
        <p className="text-center text-xs text-muted">Depois de enviar, você ainda pode corrigir até quem pediu abrir a resposta.</p>
      </form>
    </Shell>
  );
}
