// Linhas coladas na página inicial → tela de lote do modelo identificado (só neste navegador/aba).

export type IncomingBatch = { rows: Record<string, string>[]; ignored: string[] };

const key = (generatorId: string) => `minuta:batch:incoming:${generatorId}`;

export function putIncomingBatch(generatorId: string, data: IncomingBatch): boolean {
  try {
    sessionStorage.setItem(key(generatorId), JSON.stringify(data));
    return true;
  } catch {
    return false; // cota cheia ou armazenamento bloqueado
  }
}

export function peekIncomingBatch(generatorId: string): IncomingBatch | null {
  try {
    const raw = sessionStorage.getItem(key(generatorId));
    const parsed = raw ? (JSON.parse(raw) as IncomingBatch) : null;
    return parsed && Array.isArray(parsed.rows) ? parsed : null;
  } catch {
    return null;
  }
}

export function dropIncomingBatch(generatorId: string): void {
  try {
    sessionStorage.removeItem(key(generatorId));
  } catch {
    /* nada a fazer */
  }
}
