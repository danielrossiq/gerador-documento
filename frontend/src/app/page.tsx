import type { Metadata } from "next";
import { DM_Sans, Space_Grotesk } from "next/font/google";
import Link from "next/link";
import { SiteHeader } from "@/components/landing/site-header";
import { SiteImage } from "@/components/landing/site-image";

// Fontes só da landing (spec do Design); o app autenticado mantém a fonte do sistema.
const display = Space_Grotesk({ subsets: ["latin"], variable: "--lp-font-display", display: "swap" });
const body = DM_Sans({ subsets: ["latin"], variable: "--lp-font-body", display: "swap" });

export const metadata: Metadata = {
  title: { absolute: "Minuta — do seu modelo ao documento pronto para revisar" },
  description: "Transforme modelos .docx em formulários de preenchimento e gere documentos em Word ou PDF.",
};

/*
 * Landing pública (spec: Shared/DanielRossi/docs/design/minuta-site/landing-spec.md).
 * Sem guarda de sessão: visitante autenticado também vê a página e segue por "Entrar" → /dashboard.
 * Copy restrita ao que o produto faz hoje: sem preço, disponibilidade, LGPD, IA, importação de PDF
 * ou aconselhamento jurídico.
 */

const STEPS = [
  { title: "Adicione um modelo .docx.", text: "Comece pelo documento que seu escritório já usa." },
  { title: "Defina os campos.", text: "Marque as informações que serão preenchidas." },
  { title: "Preencha e gere.", text: "Confira os dados e baixe em DOCX ou PDF." },
];

const FEATURES: { title: string; text: string; image?: string }[] = [
  {
    title: "Lote por planilha",
    text: "Use uma planilha para preencher várias linhas e gerar documentos em conjunto.",
    image: "batch-spreadsheet",
  },
  { title: "Kits", text: "Reúna modelos relacionados e preencha informações compartilhadas uma vez.", image: "kits-history" },
  { title: "Histórico", text: "Encontre execuções anteriores e retome o que estiver disponível." },
];

const FAQ = [
  { q: "O que preciso para começar?", a: "Um modelo .docx que você usa no escritório." },
  {
    q: "Posso gerar mais de um documento?",
    a: "Sim. O fluxo de lote usa uma planilha; kits agrupam modelos relacionados.",
  },
  { q: "Quais arquivos posso gerar?", a: "No fluxo individual, DOCX ou PDF." },
];

export default function Landing() {
  return (
    <div className={`landing ${display.variable} ${body.variable}`}>
      <SiteHeader />
      <main id="main">
        <section aria-labelledby="hero-title" className="lp-section">
          <div className="lp-container lp-hero">
            <div>
              <p className="lp-eyebrow">Documentos do escritório, com um fluxo mais claro</p>
              <h1 id="hero-title" className="lp-h1">
                Do seu modelo ao documento pronto para revisar.
              </h1>
              <p className="lp-lead">Transforme modelos .docx em formulários de preenchimento e gere documentos em Word ou PDF.</p>
              <div className="lp-actions">
                <Link href="/register" className="lp-btn lp-btn-primary">
                  Criar conta
                </Link>
                <a href="#como-funciona" className="lp-btn lp-btn-secondary">
                  Ver como funciona
                </a>
              </div>
              <p className="lp-note">Você prepara o modelo e revisa o documento gerado.</p>
            </div>
            <SiteImage slug="hero-document-flow" priority sizes="(min-width: 1024px) 560px, 100vw" className="lp-img" />
          </div>
        </section>

        <section id="como-funciona" aria-labelledby="como-title" className="lp-section lp-alt">
          <div className="lp-container">
            <h2 id="como-title" className="lp-h2">
              Um fluxo simples, do modelo à revisão.
            </h2>
            <SiteImage slug="workflow-model-fields" sizes="(min-width: 1240px) 1200px, 100vw" className="lp-img lp-img-wide" />
            <ol className="lp-grid3 lp-steps">
              {STEPS.map((s, i) => (
                <li key={s.title} className="lp-step">
                  <span className="lp-step-num" aria-hidden>
                    {i + 1}
                  </span>
                  <h3 className="lp-h3">{s.title}</h3>
                  <p>{s.text}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section id="recursos" aria-labelledby="recursos-title" className="lp-section">
          <div className="lp-container">
            <h2 id="recursos-title" className="lp-h2">
              Para rotinas com mais de um documento.
            </h2>
            <ul className="lp-grid3">
              {FEATURES.map((f) => (
                <li key={f.title} className="lp-card">
                  {f.image && <SiteImage slug={f.image} sizes="(min-width: 1024px) 380px, 100vw" className="lp-img lp-card-img" />}
                  <h3 className="lp-h3">{f.title}</h3>
                  <p>{f.text}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section aria-labelledby="revisao-title" className="lp-section lp-band">
          <div className="lp-container lp-narrow">
            <h2 id="revisao-title" className="lp-h2">
              O documento continua sob sua revisão.
            </h2>
            <p className="lp-lead">
              Minuta organiza o preenchimento do modelo. Confira o conteúdo e o resultado antes de usar cada documento.
            </p>
          </div>
        </section>

        <section id="perguntas-frequentes" aria-labelledby="faq-title" className="lp-section">
          <div className="lp-container lp-narrow">
            <h2 id="faq-title" className="lp-h2">
              Perguntas frequentes
            </h2>
            <div className="lp-faq">
              {FAQ.map((f) => (
                <details key={f.q}>
                  <summary>{f.q}</summary>
                  <p>{f.a}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        <section aria-labelledby="cta-title" className="lp-section lp-alt">
          <div className="lp-container lp-narrow lp-center">
            <h2 id="cta-title" className="lp-h2">
              Comece pelo modelo que você já tem.
            </h2>
            <p className="lp-lead">Prepare os campos, preencha e revise o documento gerado.</p>
            <div className="lp-actions lp-actions-center">
              <Link href="/register" className="lp-btn lp-btn-primary">
                Criar conta
              </Link>
            </div>
          </div>
        </section>
      </main>
      <footer className="lp-footer">
        <div className="lp-container flex flex-wrap items-center justify-between gap-4 py-8">
          <span className="lp-brand">Minuta</span>
          <nav aria-label="Rodapé">
            <ul className="flex gap-6">
              <li>
                <Link href="/login" className="lp-navlink lp-target">
                  Entrar
                </Link>
              </li>
              <li>
                <Link href="/register" className="lp-navlink lp-target">
                  Criar conta
                </Link>
              </li>
            </ul>
          </nav>
        </div>
      </footer>
    </div>
  );
}
