import type { Metadata } from "next";
import { DM_Sans, Space_Grotesk } from "next/font/google";
import Link from "next/link";
import { HeroMedia } from "@/components/landing/hero-media";
import { Brand, SiteHeader } from "@/components/landing/site-header";
import { Picture } from "@/components/landing/site-image";
import { featureImages, heroPoster, siteCaptures, stepImages } from "@/components/landing/site-media";

// Fontes só da landing (spec do Design); o app autenticado mantém a fonte do sistema.
const display = Space_Grotesk({ subsets: ["latin"], variable: "--lp-font-display", display: "swap" });
const body = DM_Sans({ subsets: ["latin"], variable: "--lp-font-body", display: "swap" });

export const metadata: Metadata = {
  title: { absolute: "Minuta — do seu modelo ao documento pronto para revisar" },
  description: "Transforme modelos .docx em formulários de preenchimento e gere documentos em Word ou PDF.",
};

/*
 * Landing pública (specs: Shared/DanielRossi/docs/design/minuta-site/landing-spec.md e landing-spec-v2.md).
 * Sem guarda de sessão: visitante autenticado também vê a página e segue por "Entrar" → /dashboard.
 * Copy restrita ao que o produto faz hoje: sem preço, disponibilidade, LGPD, IA, importação de PDF
 * ou aconselhamento jurídico. Mídia gerada é decorativa (alt=""); sem ela, a página fica completa só com texto.
 */

const STEPS = [
  { title: "Adicione um modelo .docx.", text: "Comece pelo documento que seu escritório já usa." },
  { title: "Defina os campos.", text: "Marque as informações que serão preenchidas." },
  { title: "Preencha e gere.", text: "Confira os dados e baixe em DOCX ou PDF." },
];

const FEATURES = [
  { title: "Lote por planilha", text: "Use uma planilha para preencher várias linhas e gerar documentos em conjunto." },
  { title: "Kits", text: "Reúna modelos relacionados e preencha informações compartilhadas uma vez." },
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

const STEP_SIZES = "(min-width: 1200px) 358px, (min-width: 900px) calc((100vw - 128px) / 3), calc(100vw - 40px)";
const CARD_SIZES = "(min-width: 1200px) 358px, (min-width: 900px) calc((100vw - 128px) / 3), calc(100vw - 40px)";

export default function Landing() {
  const hero = heroPoster();
  const steps = stepImages();
  const cards = featureImages();
  const editor = siteCaptures["tela-editor-desktop"];
  const editorMobile = siteCaptures["tela-editor-mobile"];
  const form = siteCaptures["tela-preencher-mobile"];
  const screens = Boolean(editor && editorMobile && form);

  return (
    <div className={`landing ${display.variable} ${body.variable}`}>
      <SiteHeader />
      <main id="main">
        <section aria-labelledby="hero-title" className="lp-section">
          <div className={`lp-hero ${hero ? "has-media" : ""}`}>
            <div className="lp-hero-text">
              <p className="lp-eyebrow">Documentos do escritório, com um fluxo mais claro</p>
              <h1 id="hero-title" className="lp-h1">
                Do <span className="lp-field">seu modelo</span> ao documento pronto para revisar.
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
            {hero && (
              <div className="lp-hero-media">
                <HeroMedia poster={hero.poster} video={hero.video} />
              </div>
            )}
          </div>
        </section>

        <section id="como-funciona" aria-labelledby="como-title" className="lp-section lp-paper">
          <div className="lp-container">
            <h2 id="como-title" className="lp-h2">
              Um fluxo simples, do modelo à revisão.
            </h2>
            {steps.mode === "middle" && (
              <div className="lp-steps-hero">
                <Picture variants={steps.item.variants} alt="" sizes="(min-width: 1200px) 1120px, calc(100vw - 40px)" className="lp-media" />
              </div>
            )}
            <ol className={`lp-steps ${steps.mode === "three" ? "" : "is-text"}`}>
              {STEPS.map((s, i) => (
                <li key={s.title} className="lp-step">
                  {steps.mode === "three" && (
                    <Picture variants={steps.items[i].variants} alt="" sizes={STEP_SIZES} className="lp-media" />
                  )}
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

        {screens && (
          <section id="como-fica-na-tela" aria-labelledby="tela-title" className="lp-section">
            <div className="lp-container">
              <h2 id="tela-title" className="lp-h2">
                Como fica na tela.
              </h2>
              <p className="lp-lead">Você marca os campos no próprio documento e depois preenche tudo em um formulário.</p>
              <div className="lp-screens">
                <figure className="lp-shot lp-shot-desktop">
                  <Picture variants={editor.variants} alt={editor.alt} sizes="(min-width: 1200px) 730px, 66vw" />
                  <figcaption>Campos marcados no próprio modelo.</figcaption>
                </figure>
                <figure className="lp-shot lp-shot-editor-mobile">
                  <Picture variants={editorMobile.variants} alt={editorMobile.alt} sizes="(min-width: 600px) 320px, 300px" />
                  <figcaption>Campos marcados no próprio modelo.</figcaption>
                </figure>
                <figure className="lp-shot lp-shot-form-mobile">
                  <Picture variants={form.variants} alt={form.alt} sizes="(min-width: 1200px) 260px, (min-width: 600px) 320px, 300px" />
                  <figcaption>Formulário de preenchimento.</figcaption>
                </figure>
              </div>
            </div>
          </section>
        )}

        <section id="recursos" aria-labelledby="recursos-title" className="lp-section lp-paper">
          <div className="lp-container">
            <h2 id="recursos-title" className="lp-h2">
              Para rotinas com mais de um documento.
            </h2>
            <ul className="lp-cards">
              {FEATURES.map((f, i) => (
                <li key={f.title} className="lp-card">
                  {cards && <Picture variants={cards[i].variants} alt="" sizes={CARD_SIZES} className="lp-media" />}
                  <div className="lp-card-body">
                    <h3 className="lp-h3">{f.title}</h3>
                    <p>{f.text}</p>
                  </div>
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

        <section aria-labelledby="cta-title" className="lp-section lp-paper">
          <div className="lp-container lp-narrow lp-center">
            <h2 id="cta-title" className="lp-h2">
              Comece pelo <span className="lp-field">modelo</span> que você já tem.
            </h2>
            <p className="lp-lead">Prepare os campos, preencha e revise o documento gerado.</p>
            <div className="lp-actions lp-actions-center">
              <Link href="/register" className="lp-btn lp-btn-primary">
                Criar conta
              </Link>
            </div>
            <p className="lp-cta-login">
              Já tem conta?{" "}
              <Link href="/login" className="lp-link">
                Entrar
              </Link>
            </p>
          </div>
        </section>
      </main>
      <footer className="lp-footer">
        <div className="lp-container lp-footer-row">
          <Brand />
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
