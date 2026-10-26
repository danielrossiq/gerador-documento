// CSP das páginas públicas com conteúdo de terceiros (usada em src/proxy.ts).

const TURNSTILE = "https://challenges.cloudflare.com";

export function contentSecurityPolicy(nonce: string, dev: boolean): string {
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic' ${TURNSTILE}${dev ? " 'unsafe-eval'" : ""}`,
    // estilos inline do React/Tailwind (atributo style): sem nonce aqui, senão o navegador ignora o 'unsafe-inline'
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' blob: data:",
    "font-src 'self' data:",
    `connect-src 'self'${dev ? " ws: wss:" : ""}`,
    `frame-src ${TURNSTILE}`,
    "media-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
}
