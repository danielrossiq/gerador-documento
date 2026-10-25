import type { MetadataRoute } from "next";

// "Adicionar à tela inicial" no celular: nome e ícones do DocFeito (gerados por scripts/brand_export.cjs).
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "DocFeito",
    short_name: "DocFeito",
    description: "Documento feito, sem copiar e colar.",
    start_url: "/dashboard",
    display: "standalone",
    background_color: "#faf8f3",
    theme_color: "#0e1a2b",
    lang: "pt-BR",
    icons: [
      { src: "/brand/png/docfeito-icone-app-192.png", sizes: "192x192", type: "image/png" },
      { src: "/brand/png/docfeito-icone-app-512.png", sizes: "512x512", type: "image/png" },
    ],
  };
}
