import { cn } from "@/lib/utils";

// Mesma geometria de scripts/brand_build.py (folha com o canto dobrado em verde e o check subindo para a dobra).
const DOC = "M18 6H35L50 21V50A8 8 0 0 1 42 58H18A8 8 0 0 1 10 50V14A8 8 0 0 1 18 6Z";
const FLAP = "M35 6V16A5 5 0 0 0 40 21H50Z";
const CHECK = "M18 37L26 45L47 22";

/** Ícone do DocFeito. `negative` = versão para fundo escuro (folha branca, verde mais claro). */
export function LogoMark({ negative, className }: { negative?: boolean; className?: string }) {
  const doc = negative ? "#ffffff" : "#0e1a2b";
  const green = negative ? "#3ddc97" : "#12b886";
  const id = negative ? "df-mask-n" : "df-mask";
  return (
    <svg viewBox="0 0 64 64" className={cn("h-7 w-7 shrink-0", className)} aria-hidden>
      <defs>
        <mask id={id} maskUnits="userSpaceOnUse" x="0" y="0" width="64" height="64">
          <rect width="64" height="64" fill="#fff" />
          <path d={CHECK} fill="none" stroke="#000" strokeWidth="14" strokeLinecap="round" strokeLinejoin="round" />
        </mask>
      </defs>
      <path d={DOC} fill={doc} mask={`url(#${id})`} />
      <path d={FLAP} fill={green} />
      <path d={CHECK} fill="none" stroke={green} strokeWidth="7.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Marca do DocFeito: a mesma na landing, nas telas de entrada e no app. `tone` muda as cores para o fundo. */
export function Logo({ tone = "dark", compact, className }: { tone?: "dark" | "light" | "app"; compact?: boolean; className?: string }) {
  const light = tone === "light";
  return (
    <span className={cn("flex items-center gap-2 font-display text-lg font-extrabold tracking-tight", className)}>
      <LogoMark negative={light} />
      <span className={cn(compact && "hidden min-[380px]:inline")}>
        <span className={light ? "text-white" : tone === "app" ? "text-fg" : "text-ink"}>Doc</span>
        <span className={light ? "text-brand-bright" : "text-brand"}>Feito</span>
      </span>
      {compact && <span className="sr-only min-[380px]:hidden">DocFeito</span>}
    </span>
  );
}
