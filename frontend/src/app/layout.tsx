import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "@/app/providers";

export const metadata: Metadata = {
  title: { default: "Minuta — documentos que se preenchem sozinhos", template: "%s · Minuta" },
  description: "Transforme documentos repetitivos em modelos que se preenchem sozinhos, um a um, em lote ou em kits.",
  openGraph: { title: "Minuta — Documentos prontos. Tempo de volta.", description: "Transforme documentos repetitivos em modelos reutilizáveis.", images: [{ url: "/assets/og.svg", width: 1200, height: 630, alt: "Minuta — Documentos prontos. Tempo de volta." }], locale: "pt_BR", type: "website" },
  icons: { icon: "/favicon.svg" },
};
export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: `(function(){try{var t=localStorage.getItem("minuta-theme");document.documentElement.dataset.theme=t||(matchMedia("(prefers-color-scheme:dark)").matches?"dark":"light")}catch(e){}})()` }} /></head>
      <body>
        <a href="#main" className="skip-link">
          Ir para o conteúdo
        </a>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
