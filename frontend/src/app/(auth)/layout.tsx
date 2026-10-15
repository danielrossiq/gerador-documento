import { CheckCircle2, FileText } from "lucide-react";
import type { ReactNode } from "react";
import { APP_NAME } from "@/lib/utils";

const POINTS = [
  "Envie o contrato, recibo ou declaração que você já usa (Word ou PDF digitado)",
  "Nome, CPF, datas e valores viram campos sozinhos",
  "Preencha um formulário e baixe DOCX ou PDF pronto",
  "Centenas de uma vez a partir de uma planilha",
  "Kits: vários documentos com os mesmos dados, preenchidos uma vez",
];

/** Login/cadastro: à esquerda, o que o produto faz — antes a primeira tela não explicava nada. */
export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main id="main" className="grid min-h-screen lg:grid-cols-2">
      <section aria-label={`Sobre o ${APP_NAME}`} className="hidden flex-col justify-center bg-primary px-12 py-16 text-primary-fg lg:flex">
        <div className="mx-auto max-w-md">
          <div className="flex items-center gap-2">
            <FileText className="h-7 w-7" aria-hidden />
            <span className="text-2xl font-bold tracking-tight">{APP_NAME}</span>
          </div>
          <h2 className="mt-10 text-3xl font-bold leading-tight tracking-tight">Documentos que se preenchem sozinhos.</h2>
          <p className="mt-3 text-base opacity-90">Configure o modelo uma vez. Gere quantas vezes precisar — sem copiar e colar no Word.</p>
          <ul className="mt-8 space-y-3 text-sm">
            {POINTS.map((p) => (
              <li key={p} className="flex gap-2.5">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 opacity-90" aria-hidden />
                <span className="opacity-95">{p}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>
      <div className="grid place-items-center px-4 py-10">
        <div className="w-full max-w-md">
          <div className="mb-6 flex items-center justify-center gap-2 text-primary lg:hidden">
            <FileText className="h-7 w-7" aria-hidden />
            <span className="text-2xl font-bold tracking-tight">{APP_NAME}</span>
          </div>
          <div className="rounded-lg border border-border bg-surface p-7 shadow-md">{children}</div>
          <p className="mt-6 text-center text-xs text-muted lg:hidden">Documentos repetitivos viram modelos que se preenchem sozinhos.</p>
        </div>
      </div>
    </main>
  );
}
