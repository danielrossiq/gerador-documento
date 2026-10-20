import type { NextConfig } from "next";

// Mesma origem: o navegador fala só com o Next; /api/* é encaminhado à API (cookies simples, sem CORS).
// Em contêiner, API_INTERNAL_URL é passado como build arg (o destino do rewrite é fixado no build).
const API = process.env.API_INTERNAL_URL || "http://127.0.0.1:8100";

const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "same-origin" },
          // Só restringe áudio/vídeo à mesma origem (vídeo da landing em /site/). A CSP completa, com nonces,
          // é o item 16 do docs/BACKLOG.md e depende de Security review.
          { key: "Content-Security-Policy", value: "media-src 'self'" },
        ],
      },
    ];
  },
};

export default config;
