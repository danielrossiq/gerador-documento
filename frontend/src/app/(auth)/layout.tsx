import { CheckCircle2 } from "lucide-react";
import type { ReactNode } from "react";
import { Logo } from "@/components/brand/logo";
import { APP_NAME } from "@/lib/utils";

const POINTS = [
  "Envie o contrato, recibo ou procuração que você já usa",
  "A IA marca nome, CPF, datas e valores para você",
  "Cole o WhatsApp do cliente e o formulário se preenche",
  "Word ou PDF pronto, um a um ou centenas por planilha",
];

/** Trecho de documento com os campos destacados, como na landing: mostra o produto já na entrada. */
function DocSnippet() {
  const chip = "rounded px-1 py-0.5 font-medium text-white ring-1";
  return (
    <div aria-hidden className="mt-10 rounded-xl border border-white/10 bg-white/[0.04] p-5 text-[13px] leading-7 text-zinc-300 shadow-2xl backdrop-blur">
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-zinc-500">Contrato de prestação de serviços</p>
      <p>
        <span className="font-semibold text-white">CONTRATANTE:</span> <span className={`${chip} bg-indigo-500/30 ring-indigo-400/50`}>Marina Duarte Campos</span>,
        inscrita no CPF sob o nº <span className={`${chip} bg-emerald-500/25 ring-emerald-400/50`}>529.982.247-25</span>, residente em{" "}
        <span className={`${chip} bg-indigo-500/30 ring-indigo-400/50`}>Belo Horizonte/MG</span>.
      </p>
      <p className="mt-1">
        Valor mensal de <span className={`${chip} bg-amber-500/25 ring-amber-400/50`}>R$ 3.200,00</span> (três mil e duzentos reais), a partir de{" "}
        <span className={`${chip} bg-sky-500/25 ring-sky-400/50`}>10 de novembro de 2026</span>.
      </p>
    </div>
  );
}

/** Login/cadastro: à esquerda, o que o produto faz, no mesmo visual da landing. */
export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main id="main" className="grid min-h-screen lg:grid-cols-2">
      <section aria-label={`Sobre o ${APP_NAME}`} className="site-hero relative hidden flex-col justify-center overflow-hidden bg-zinc-950 px-12 py-16 text-white lg:flex">
        <div aria-hidden className="site-hero-glow pointer-events-none absolute inset-0" />
        <div className="relative mx-auto max-w-md">
          <Logo tone="light" className="text-2xl" />
          <h2 className="mt-10 font-display text-4xl font-extrabold leading-tight tracking-tight">
            Documentos que se <span className="site-chip">preenchem sozinhos.</span>
          </h2>
          <p className="mt-4 text-base text-zinc-300">Configure o modelo uma vez. Gere quantas vezes precisar, sem copiar e colar no Word.</p>
          <ul className="mt-8 space-y-3 text-sm">
            {POINTS.map((p) => (
              <li key={p} className="flex gap-2.5">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" aria-hidden />
                <span className="text-zinc-200">{p}</span>
              </li>
            ))}
          </ul>
          <DocSnippet />
        </div>
      </section>
      <div className="grid place-items-center px-4 py-10">
        <div className="w-full max-w-md">
          <div className="mb-6 flex justify-center lg:hidden">
            <Logo tone="app" className="text-2xl" />
          </div>
          <div className="rounded-xl border border-border bg-surface p-7 shadow-md">{children}</div>
          <p className="mt-6 text-center text-xs text-muted lg:hidden">Documentos repetitivos viram modelos que se preenchem sozinhos.</p>
        </div>
      </div>
    </main>
  );
}
