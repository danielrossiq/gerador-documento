import { cn } from "@/lib/utils";

/** Marca do Minuta: a mesma na landing, nas telas de entrada e no app. `tone` só muda a cor do nome. */
export function Logo({ tone = "dark", compact, className }: { tone?: "dark" | "light" | "app"; compact?: boolean; className?: string }) {
  return (
    <span
      className={cn(
        "flex items-center gap-2 font-display text-lg font-extrabold tracking-tight",
        tone === "light" ? "text-white" : tone === "app" ? "text-fg" : "text-zinc-900",
        className,
      )}
    >
      <svg viewBox="0 0 32 32" className="h-7 w-7 shrink-0" aria-hidden>
        <rect width="32" height="32" rx="8" fill="#4f46e5" />
        <path d="M10 8.5h8.5L23 13v10.5a1 1 0 0 1-1 1H10a1 1 0 0 1-1-1v-14a1 1 0 0 1 1-1Z" fill="#fff" />
        <rect x="12" y="15" width="8" height="2.4" rx="1.2" fill="#a5b4fc" />
        <rect x="12" y="19" width="5.5" height="2.4" rx="1.2" fill="#34d399" />
      </svg>
      <span className={cn(compact && "hidden min-[380px]:inline")}>Minuta</span>
      {compact && <span className="sr-only min-[380px]:hidden">Minuta</span>}
    </span>
  );
}
