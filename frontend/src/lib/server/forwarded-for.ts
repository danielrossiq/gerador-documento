import http from "node:http";

/*
 * IP do cliente para a API (limites por IP do cadastro, do teste grátis e do link do cliente).
 *
 * O rewrite de /api/* do Next repassa os cabeçalhos do navegador como vieram e não acrescenta o endereço de quem
 * conectou: a API veria um X-Forwarded-For escrito pelo próprio cliente (falsificável) ou, sem ele, o IP do Next
 * para todo mundo. Aqui o servidor do Next ACRESCENTA ao X-Forwarded-For o endereço do socket, como o nginx faz
 * com `$proxy_add_x_forwarded_for`. A API (app/core/net.py) lê o cabeçalho da direita para a esquerda e para no
 * primeiro endereço que não é um proxy confiável: o que o cliente escreveu fica à esquerda e é ignorado.
 */

const MARK = Symbol.for("docfeito.forwarded-for");

/** Valor novo do X-Forwarded-For: o anterior (se houver) + o endereço de quem abriu a conexão. */
export function appendForwardedFor(current: string | string[] | undefined, remote: string | undefined): string {
  const prev = (Array.isArray(current) ? current.join(", ") : current ?? "").trim();
  // sem endereço do socket (não deveria acontecer): um marcador inválido faz a API usar o IP do próprio Next
  const addr = (remote ?? "").trim() || "unknown";
  return prev ? `${prev}, ${addr}` : addr;
}

type Emit = (this: http.Server, event: string | symbol, ...args: unknown[]) => boolean;

/** Instala uma vez por processo, antes de qualquer outro tratamento da requisição (ver instrumentation.ts). */
export function installForwardedFor(): void {
  const proto = http.Server.prototype as unknown as { emit: Emit; [MARK]?: boolean };
  if (proto[MARK]) return;
  const original = proto.emit;
  proto.emit = function (this: http.Server, event: string | symbol, ...args: unknown[]) {
    if (event === "request") {
      const req = args[0] as http.IncomingMessage & { [MARK]?: boolean };
      if (!req[MARK]) {
        req[MARK] = true;
        req.headers["x-forwarded-for"] = appendForwardedFor(req.headers["x-forwarded-for"], req.socket?.remoteAddress);
      }
    }
    return original.call(this, event, ...args);
  };
  proto[MARK] = true;
}
