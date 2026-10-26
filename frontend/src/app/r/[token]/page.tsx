import type { Metadata } from "next";
import { ClientForm } from "@/components/requests/client-form";

// Página do cliente (D39): pública, sem login. Renderizada por requisição (a CSP com nonce vem de src/proxy.ts).
export const metadata: Metadata = {
  title: "Preencher dados",
  robots: { index: false, follow: false },
  referrer: "no-referrer", // o token está no endereço: não vaza para sites de fora
};

export default async function ClientRequestPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <ClientForm token={token} />;
}
