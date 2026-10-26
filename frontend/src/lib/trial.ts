// Teste grátis da landing (D38): tipos da API pública e o "guardar na conta" depois do cadastro/login.

import { api } from "@/lib/api";
import type { DocNode } from "@/lib/types";

export type TrialConfig = {
  enabled: boolean;
  max_mb: number;
  max_pages: number;
  accepts_pdf: boolean;
  turnstile_site_key: string | null;
  ttl_minutes: number;
};

export type TrialField = {
  id: string;
  name: string;
  label: string;
  type: string;
  sample: string;
  count: number;
  source: string;
  confidence: number;
};

export type TrialStatus = {
  status: "queued" | "processing" | "done" | "failed";
  filename: string;
  format: "docx" | "pdf";
  expires_at: string;
  ai: "ai" | "local" | "budget" | "rules" | null;
  error: { code: string; message: string } | null;
  result: { doc: DocNode; fields: TrialField[]; warnings: string[]; stats: { paragraphs: number; fields: number } } | null;
};

/** Token do teste no formato que a API gera (secrets.token_urlsafe(32)): evita levar lixo da URL adiante. */
export function validTrialToken(token: string | null | undefined): token is string {
  return !!token && /^[A-Za-z0-9_-]{40,64}$/.test(token);
}

/** Depois do cadastro/login: o documento do teste vira modelo da conta. Devolve a rota da etapa Campos. */
export async function claimTrial(token: string): Promise<string> {
  const r = await api.post<{ generator_id: string; next: string }>(`/trials/${encodeURIComponent(token)}/claim`);
  return r.next.startsWith("/generators/") ? r.next : `/generators/${r.generator_id}/edit`;
}
