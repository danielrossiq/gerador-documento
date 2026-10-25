import type { Metadata, Viewport } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";
import { Providers } from "@/app/providers";

export const metadata: Metadata = {
  title: { default: "DocFeito — documento feito, sem copiar e colar", template: "%s · DocFeito" },
  description: "Transforme documentos repetitivos em modelos que se preenchem sozinhos, um a um, em lote ou em kits.",
  icons: {
    icon: [
      { url: "/favicon.svg", type: "image/svg+xml" },
      { url: "/favicon.ico", sizes: "48x48" },
    ],
    apple: "/apple-touch-icon.png",
  },
};
export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#0e1a2b" };

// fonte de títulos e da marca em todo o produto (landing, entrada e app); o texto corrido segue na fonte do sistema
const display = Plus_Jakarta_Sans({ subsets: ["latin"], weight: ["600", "700", "800"], variable: "--site-display", display: "swap" });

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR" className={display.variable}>
      <body>
        <a href="#main" className="skip-link">
          Ir para o conteúdo
        </a>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
