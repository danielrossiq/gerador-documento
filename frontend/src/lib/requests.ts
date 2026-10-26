// Link para o cliente preencher (D39): tipos da API e utilidades de compartilhamento.

import type { FieldOut } from "@/lib/types";

export type RequestState = "open" | "answered" | "expired" | "cancelled" | "used";

export type ClientRequestOut = {
  id: string;
  target: { type: "generator" | "kit"; id: string; name: string };
  state: RequestState;
  fields: string[];
  message: string | null;
  allow_photos: boolean;
  photo_reads: number;
  prefill_mode: "hidden" | "readonly" | "editable";
  submissions: number;
  created_at: string;
  expires_at: string;
  answered_at: string | null;
  opened_at: string | null;
  used_at: string | null;
  has_values: boolean;
};

export type ClientRequestCreated = ClientRequestOut & { url: string; share_text: string };
export type ClientRequestOpened = ClientRequestOut & { values: Record<string, unknown>; prefill: Record<string, unknown> };

export type PublicRequest =
  | { state: "expired" }
  | { state: "closed" }
  | {
      state: "open" | "answered";
      workspace: string;
      document: string;
      message: string | null;
      fields: FieldOut[];
      prefill_mode: "hidden" | "readonly" | "editable";
      prefill: Record<string, unknown>;
      values: Record<string, unknown>;
      photos: { allowed: boolean; reads_left: number };
      expires_at: string;
    };

export const STATE_LABEL: Record<RequestState, string> = {
  open: "Aguardando o cliente",
  answered: "Respondido",
  expired: "Expirado",
  cancelled: "Cancelado",
  used: "Usado",
};

/** Link do WhatsApp com a mensagem pronta (o profissional escolhe o contato no próprio WhatsApp). */
export function whatsappUrl(text: string): string {
  return `https://wa.me/?text=${encodeURIComponent(text)}`;
}

/** Rota da tela Gerar com a resposta carregada no formulário. */
export function answerHref(r: Pick<ClientRequestOut, "id" | "target">): string {
  return r.target.type === "kit" ? `/kits/${r.target.id}/use?request=${r.id}` : `/generators/${r.target.id}/use?request=${r.id}`;
}

export function shortDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}
