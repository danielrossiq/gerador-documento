"use client";

import { Menu, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

const ANCHORS = [
  { href: "#como-funciona", label: "Como funciona" },
  { href: "#recursos", label: "Recursos" },
  { href: "#perguntas-frequentes", label: "Perguntas frequentes" },
];

/** Marca tipográfica com a lacuna âmbar decorativa (landing-spec-v2 §3.2). */
export function Brand({ className = "" }: { className?: string }) {
  return (
    <Link href="/" className={`lp-brand ${className}`}>
      <span className="lp-brand-word">Minuta</span>
    </Link>
  );
}

/**
 * Cabeçalho da landing: âncoras inteiras a partir de 1024 px; abaixo, num menu com estado anunciado (aria-expanded).
 * Abaixo de 380 px, "Entrar" sai da barra e vira o primeiro item do menu (continua no rodapé e no CTA final).
 */
export function SiteHeader() {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        button.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <header className="lp-header">
      <div className="lp-container lp-header-row">
        <Brand />
        <nav aria-label="Seções da página" className="hidden lg:block">
          <ul className="flex gap-7">
            {ANCHORS.map((a) => (
              <li key={a.href}>
                <a href={a.href} className="lp-navlink lp-target">
                  {a.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <div className="lp-header-actions">
          <Link href="/login" className="lp-navlink lp-target lp-header-login">
            Entrar
          </Link>
          <Link href="/register" className="lp-btn lp-btn-primary lp-btn-sm">
            Criar conta
          </Link>
          <button
            ref={button}
            type="button"
            className="lp-menu-btn lg:hidden"
            aria-expanded={open}
            aria-controls="lp-mobile-nav"
            onClick={() => setOpen((v) => !v)}
          >
            {open ? <X className="h-5 w-5" aria-hidden /> : <Menu className="h-5 w-5" aria-hidden />}
            <span className="sr-only">{open ? "Fechar menu" : "Abrir menu"}</span>
          </button>
        </div>
      </div>
      <nav id="lp-mobile-nav" aria-label="Menu de seções" hidden={!open} className="lg:hidden">
        <ul className="lp-container flex flex-col pb-4">
          <li className="lp-menu-login">
            <Link href="/login" className="lp-mobile-link">
              Entrar
            </Link>
          </li>
          {ANCHORS.map((a) => (
            <li key={a.href}>
              <a href={a.href} className="lp-mobile-link" onClick={() => setOpen(false)}>
                {a.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>
    </header>
  );
}
