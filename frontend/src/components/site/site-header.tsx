"use client";

import { Menu, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "#demo", label: "Testar agora" },
  { href: "#como-funciona", label: "Como funciona" },
  { href: "#recursos", label: "Recursos" },
  { href: "#precos", label: "Preços" },
  { href: "#perguntas", label: "Dúvidas" },
];

export function Logo({ light }: { light?: boolean }) {
  return (
    <span className={cn("flex items-center gap-2 font-display text-lg font-extrabold tracking-tight", light ? "text-white" : "text-zinc-900")}>
      <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden>
        <rect width="32" height="32" rx="8" fill="#4f46e5" />
        <path d="M10 8.5h8.5L23 13v10.5a1 1 0 0 1-1 1H10a1 1 0 0 1-1-1v-14a1 1 0 0 1 1-1Z" fill="#fff" />
        <rect x="12" y="15" width="8" height="2.4" rx="1.2" fill="#a5b4fc" />
        <rect x="12" y="19" width="5.5" height="2.4" rx="1.2" fill="#34d399" />
      </svg>
      Minuta
    </span>
  );
}

export function SiteHeader() {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    const raf = requestAnimationFrame(onScroll); // página aberta já rolada (ex.: voltar no navegador)
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("scroll", onScroll);
    };
  }, []);

  const light = !scrolled && !open;

  return (
    <header className={cn("fixed inset-x-0 top-0 z-50 transition-colors duration-300", light ? "bg-transparent" : "border-b border-zinc-200/70 bg-white/90 backdrop-blur-lg")}>
      <div className="mx-auto flex h-16 max-w-7xl items-center gap-6 px-5">
        <Link href="/" aria-label="Minuta — início">
          <Logo light={light} />
        </Link>
        <nav aria-label="Seções" className="hidden items-center gap-1 lg:flex">
          {NAV.map((n) => (
            <a key={n.href} href={n.href} className={cn("rounded-full px-3 py-1.5 text-sm font-medium transition", light ? "text-zinc-300 hover:text-white" : "text-zinc-600 hover:text-zinc-900")}>
              {n.label}
            </a>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <Link href="/login" className={cn("hidden rounded-full px-4 py-2 text-sm font-semibold transition sm:block", light ? "text-white hover:bg-white/10" : "text-zinc-700 hover:bg-zinc-100")}>
            Entrar
          </Link>
          <Link href="/register" className="rounded-full bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-indigo-600/25 transition hover:bg-indigo-500" data-testid="header-cta">
            Começar grátis
          </Link>
          <button
            className={cn("grid h-9 w-9 place-items-center rounded-full lg:hidden", light ? "text-white" : "text-zinc-700")}
            aria-label={open ? "Fechar menu" : "Abrir menu"}
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
          >
            {open ? <X className="h-5 w-5" aria-hidden /> : <Menu className="h-5 w-5" aria-hidden />}
          </button>
        </div>
      </div>
      {open && (
        <nav aria-label="Seções" className="border-t border-zinc-200 bg-white px-5 pb-5 lg:hidden">
          {NAV.map((n) => (
            <a key={n.href} href={n.href} onClick={() => setOpen(false)} className="block border-b border-zinc-100 py-3 text-base font-medium text-zinc-800">
              {n.label}
            </a>
          ))}
          <Link href="/login" className="block py-3 text-base font-medium text-zinc-800">Entrar</Link>
        </nav>
      )}
    </header>
  );
}
