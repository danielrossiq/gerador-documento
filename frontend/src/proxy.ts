import { NextResponse, type NextRequest } from "next/server";
import { contentSecurityPolicy } from "@/lib/csp";

/*
 * CSP com nonce nas páginas públicas que mostram conteúdo de terceiros (requisito OBR-8 da segurança): a landing,
 * onde o visitante vê o próprio documento no teste grátis, e o link do cliente (/r/…). Script só com o nonce desta
 * resposta (sem 'unsafe-inline'); 'strict-dynamic' deixa os scripts do Next carregarem o widget do Turnstile.
 * O conteúdo do documento é sempre texto escapado pelo React (nada de dangerouslySetInnerHTML).
 */

export function proxy(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const csp = contentSecurityPolicy(nonce, process.env.NODE_ENV === "development");
  const headers = new Headers(request.headers);
  headers.set("x-nonce", nonce);
  headers.set("Content-Security-Policy", csp); // o Next lê o nonce daqui e o aplica aos próprios scripts
  const response = NextResponse.next({ request: { headers } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  matcher: [
    {
      source: "/",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
    {
      source: "/r/:path*",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
