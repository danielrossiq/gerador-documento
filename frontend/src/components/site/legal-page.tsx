import Link from "next/link";
import type { ReactNode } from "react";
import { Logo } from "@/components/site/site-header";

/** Moldura das páginas legais do site (texto preliminar, sinalizado como tal). */
export function LegalPage({ title, updated, children }: { title: string; updated: string; children: ReactNode }) {
  return (
    <div className="min-h-screen bg-white text-zinc-800">
      <header className="border-b border-zinc-200">
        <div className="mx-auto flex h-16 max-w-3xl items-center px-5">
          <Link href="/" aria-label="Minuta — início">
            <Logo />
          </Link>
        </div>
      </header>
      <main id="main" className="mx-auto max-w-3xl px-5 py-12">
        <h1 className="text-3xl font-bold tracking-tight text-zinc-900">{title}</h1>
        <p className="mt-2 text-sm text-zinc-500">Última atualização: {updated}</p>
        <p className="mt-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          Versão preliminar, em revisão jurídica. Descreve como o produto funciona hoje; pode mudar antes do lançamento comercial.
        </p>
        <div className="legal mt-8 space-y-4 leading-relaxed [&_h2]:mt-8 [&_h2]:text-xl [&_h2]:font-bold [&_h2]:text-zinc-900 [&_li]:ml-5 [&_li]:list-disc">{children}</div>
      </main>
    </div>
  );
}
