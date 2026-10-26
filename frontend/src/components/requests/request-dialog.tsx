"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Link2, MessageCircle, Send } from "lucide-react";
import { useMemo, useState } from "react";
import { Button, ButtonAnchor } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/form";
import { Alert } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { shortDate, whatsappUrl, type ClientRequestCreated } from "@/lib/requests";
import type { FieldOut } from "@/lib/types";

const DAYS = [1, 3, 7, 15, 30];
const filled = (v: unknown) => v !== undefined && v !== null && v !== "" && v !== false;

/**
 * "Pedir dados ao cliente" (D39): escolhe os campos, a mensagem e a validade e cria um link para o cliente preencher
 * pelo celular. O link aparece uma vez (no servidor fica só o hash do token): copiar ou mandar pelo WhatsApp.
 */
export function RequestDialog({
  open,
  onOpenChange,
  target,
  targetId,
  fields,
  currentValues,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  target: "generator" | "kit";
  targetId: string;
  fields: FieldOut[];
  currentValues: () => Record<string, unknown>;
}) {
  const toast = useToast();
  const qc = useQueryClient();
  const ai = useQuery({ queryKey: ["assist-status"], queryFn: () => api.get<{ enabled: boolean }>("/assist/status"), staleTime: 60_000 });
  const defaults = useMemo(() => {
    const req = fields.filter((f) => f.required && (f.default_value === null || f.default_value === undefined || f.default_value === ""));
    return new Set((req.length ? req : fields).map((f) => f.name));
  }, [fields]);
  const [picked, setPicked] = useState<Set<string>>(defaults);
  const [message, setMessage] = useState("");
  const [days, setDays] = useState(7);
  const [photos, setPhotos] = useState(false);
  const [prefillMode, setPrefillMode] = useState<"hidden" | "readonly" | "editable">("hidden");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<ClientRequestCreated | null>(null);
  const [copied, setCopied] = useState<"link" | "text" | null>(null);

  const values = open ? currentValues() : {};
  const alreadyFilled = fields.filter((f) => picked.has(f.name) && filled(values[f.name]));

  function reset() {
    setPicked(defaults);
    setMessage("");
    setDays(7);
    setPhotos(false);
    setPrefillMode("hidden");
    setError(null);
    setCreated(null);
    setCopied(null);
  }

  function toggle(name: string) {
    setPicked((s) => {
      const n = new Set(s);
      if (n.has(name)) n.delete(name);
      else n.add(name);
      return n;
    });
  }

  async function submit() {
    if (picked.size === 0) {
      setError("Escolha pelo menos um campo para o cliente preencher.");
      return;
    }
    setBusy(true);
    setError(null);
    const prefill = Object.fromEntries(alreadyFilled.map((f) => [f.name, values[f.name]]));
    try {
      const path = target === "kit" ? `/kits/${targetId}/client-requests` : `/generators/${targetId}/client-requests`;
      const r = await api.post<ClientRequestCreated>(path, {
        fields: fields.filter((f) => picked.has(f.name)).map((f) => f.name),
        message: message.trim() || null,
        expires_days: days,
        allow_photos: photos,
        prefill: prefillMode === "hidden" ? {} : prefill,
        prefill_mode: prefillMode,
      });
      setCreated(r);
      void qc.invalidateQueries({ queryKey: ["client-requests"] });
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function copy(text: string, what: "link" | "text") {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(what);
      toast.push({ tone: "success", title: what === "link" ? "Link copiado" : "Mensagem copiada" });
    } catch {
      toast.push({ tone: "danger", title: "Não foi possível copiar", description: "Selecione o link e copie com Ctrl+C." });
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) reset();
        onOpenChange(o);
      }}
      title={created ? "Link pronto para enviar" : "Pedir dados ao cliente"}
      description={created ? undefined : "O cliente preenche pelo celular (ou manda a foto do documento) e a resposta volta para cá. Você confere antes de gerar."}
      size="lg"
      footer={
        created ? (
          <Button variant="primary" onClick={() => onOpenChange(false)}>Concluir</Button>
        ) : (
          <>
            <Button onClick={() => onOpenChange(false)}>Cancelar</Button>
            <Button variant="primary" loading={busy} onClick={submit} data-testid="request-create">
              <Link2 className="h-4 w-4" aria-hidden /> Criar link
            </Button>
          </>
        )
      }
    >
      {created ? (
        <div className="space-y-4" data-testid="request-created">
          <Field label="Link para o cliente" help={`Vale até ${shortDate(created.expires_at)}. Por segurança, ele aparece só agora: copie ou envie antes de fechar.`}>
            {(a) => <Input readOnly value={created.url} onFocus={(e) => e.currentTarget.select()} data-testid="request-url" {...a} />}
          </Field>
          <div className="flex flex-wrap gap-2">
            <ButtonAnchor href={whatsappUrl(created.share_text)} target="_blank" rel="noopener noreferrer" variant="primary" data-testid="request-whatsapp">
              <MessageCircle className="h-4 w-4" aria-hidden /> Enviar pelo WhatsApp
            </ButtonAnchor>
            <Button onClick={() => copy(created.share_text, "text")} data-testid="request-copy-text">
              {copied === "text" ? <Check className="h-4 w-4" aria-hidden /> : <Copy className="h-4 w-4" aria-hidden />} Copiar mensagem para WhatsApp
            </Button>
            <Button onClick={() => copy(created.url, "link")} data-testid="request-copy-link">
              {copied === "link" ? <Check className="h-4 w-4" aria-hidden /> : <Copy className="h-4 w-4" aria-hidden />} Copiar link
            </Button>
          </div>
          <Alert tone="primary">Quando o cliente enviar, a resposta aparece em “Respostas recebidas”, aqui e no Início.</Alert>
        </div>
      ) : (
        <div className="space-y-5">
          {error && <Alert tone="danger">{error}</Alert>}
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Quais dados pedir</legend>
            <div className="flex flex-wrap gap-2 text-xs">
              <button type="button" className="text-primary underline" onClick={() => setPicked(new Set(fields.map((f) => f.name)))}>Marcar todos</button>
              <button type="button" className="text-primary underline" onClick={() => setPicked(defaults)}>Só os obrigatórios</button>
            </div>
            <div className="grid max-h-56 gap-1.5 overflow-auto rounded-md border border-border p-3 sm:grid-cols-2" data-testid="request-fields">
              {fields.map((f) => (
                <Checkbox key={f.name} label={<>{f.label}{f.required && <span className="text-danger" aria-hidden> *</span>}</>} checked={picked.has(f.name)} onChange={() => toggle(f.name)} />
              ))}
            </div>
            <p className="text-xs text-muted">{picked.size} de {fields.length} campos. O cliente vê só estes rótulos — nada do restante do documento.</p>
          </fieldset>
          <Field label="Mensagem para o cliente" help="Opcional. Aparece no topo da página do cliente.">
            {(a) => <Textarea maxLength={1000} placeholder="Ex.: Oi, Maria! Preencha seus dados para o contrato de locação." value={message} onChange={(e) => setMessage(e.target.value)} {...a} />}
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Validade do link">
              {(a) => (
                <Select value={days} onChange={(e) => setDays(Number(e.target.value))} {...a}>
                  {DAYS.map((d) => <option key={d} value={d}>{d === 1 ? "1 dia" : `${d} dias`}{d === 7 ? " (padrão)" : ""}</option>)}
                </Select>
              )}
            </Field>
            {ai.data?.enabled && (
              <div className="space-y-1 pt-6">
                <Checkbox label="Permitir enviar a foto do documento (RG, CNH, comprovante)" checked={photos} onChange={(e) => setPhotos(e.target.checked)} data-testid="request-photos" />
                <p className="pl-6 text-xs text-muted">A IA lê a foto e preenche. Até 3 leituras por link, contando na cota de IA do seu plano.</p>
              </div>
            )}
          </div>
          {alreadyFilled.length > 0 && (
            <fieldset className="space-y-1.5">
              <legend className="text-sm font-medium">Você já preencheu {alreadyFilled.length} {alreadyFilled.length === 1 ? "desses campos" : "desses campos"}. O cliente…</legend>
              {(
                [
                  ["hidden", "não vê esses valores (preenche do zero)"],
                  ["readonly", "vê, mas não pode mudar"],
                  ["editable", "vê e pode corrigir"],
                ] as const
              ).map(([v, label]) => (
                <label key={v} className="flex cursor-pointer items-center gap-2 text-sm">
                  <input type="radio" name="prefill" className="h-4 w-4 accent-[var(--primary)]" checked={prefillMode === v} onChange={() => setPrefillMode(v)} />
                  {label}
                </label>
              ))}
            </fieldset>
          )}
          <p className="flex items-start gap-2 text-xs text-muted">
            <Send className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /> O link é pessoal: quem tiver o link consegue preencher. Você pode cancelar quando quiser.
          </p>
        </div>
      )}
    </Dialog>
  );
}
