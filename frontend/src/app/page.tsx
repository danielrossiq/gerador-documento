import {
  ArrowRight,
  Building2,
  Calculator,
  CheckCircle2,
  ClipboardPaste,
  FileCheck2,
  FileSpreadsheet,
  FileText,
  FileUp,
  Fingerprint,
  HeartPulse,
  History,
  KeyRound,
  Layers,
  Lock,
  Play,
  Scale,
  ScanSearch,
  ShieldCheck,
  Sparkles,
  Trash2,
  Type,
  Users,
  XCircle,
} from "lucide-react";
import type { Metadata } from "next";
import { Inter } from "next/font/google";
import Link from "next/link";
import type { ReactNode } from "react";
import { LiveDemo } from "@/components/site/live-demo";
import { DemoVideo, demoVideo, hasImage, SiteImage } from "@/components/site/media";
import { Pricing } from "@/components/site/pricing";
import { RoiCalculator } from "@/components/site/roi-calculator";
import { Logo, SiteHeader } from "@/components/site/site-header";

// Texto corrido em Inter só no site público (a fonte de títulos, Plus Jakarta, vem do layout raiz para todo o produto).
const body = Inter({ subsets: ["latin"], variable: "--site-body", display: "swap" });

export const metadata: Metadata = {
  title: { absolute: "DocFeito — documento feito, sem copiar e colar" },
  description:
    "Envie o contrato, a procuração ou o recibo que você já usa (Word ou PDF). A IA marca nome, CPF, valores e datas; você preenche um formulário e gera 1 ou 1.000 documentos prontos.",
  openGraph: {
    title: "DocFeito — documento feito, sem copiar e colar",
    description: "Pare de copiar e colar no Word. A IA transforma os documentos que você já usa em formulários: gere 1 ou 1.000 em segundos.",
    type: "website",
    locale: "pt_BR",
    images: hasImage("og") ? [{ url: "/site/og-1200.webp", width: 1200, height: 630 }] : undefined,
  },
};

const SEGMENTS = [
  { icon: Scale, label: "Advocacia" },
  { icon: Calculator, label: "Contabilidade" },
  { icon: Building2, label: "Imobiliárias" },
  { icon: Users, label: "RH e Departamento Pessoal" },
  { icon: FileCheck2, label: "Corretoras e despachantes" },
  { icon: HeartPulse, label: "Clínicas e consultórios" },
];

const BEFORE = [
  "Abrir o Word e caçar cada nome, CPF, valor e data",
  "Escrever o valor por extenso na mão (e errar)",
  "Revisar tudo de novo porque algo escapou",
  "Repetir isso para cada cliente, todo mês",
];
const AFTER = [
  "Envie o documento que você já usa, uma vez só",
  "A IA marca os campos; você só confere",
  "Preencha um formulário curto ou cole uma planilha",
  "Baixe em Word ou PDF, com a sua formatação",
];

const STEPS = [
  {
    icon: FileUp,
    title: "Envie o documento que você já usa",
    text: "Contrato, procuração, recibo, declaração… Em Word (.docx) ou PDF digitado. Cabeçalho, tabelas e logotipo continuam iguais.",
    shot: "passo-documento",
  },
  {
    icon: ScanSearch,
    title: "A IA marca o que muda",
    text: "Nomes, CPFs, valores, datas e endereços viram campos. Você confere, ajusta o que quiser e salva o modelo.",
    shot: "passo-campos",
  },
  {
    icon: FileText,
    title: "Gere um ou mil",
    text: "Preencha um formulário para um documento ou cole uma planilha para gerar centenas de uma vez, prontos para assinar.",
    shot: "passo-gerar",
  },
];

const FEATURES: { icon: typeof Sparkles; title: string; text: string; big?: boolean; tag?: string }[] = [
  {
    icon: Sparkles,
    title: "IA que entende o seu documento",
    text: "Encontra as partes, CPFs, CNPJs, valores, datas, endereços e cláusulas que mudam de um cliente para outro. Nada é aplicado sem você conferir.",
    big: true,
    tag: "IA",
  },
  {
    icon: ClipboardPaste,
    title: "Cole o texto, o formulário se preenche",
    text: "Recebeu os dados do cliente por e-mail ou WhatsApp? Cole a mensagem e a IA distribui cada informação no campo certo.",
    tag: "IA",
  },
  {
    icon: ShieldCheck,
    title: "Revisão antes de gerar",
    text: "A IA aponta o que parece errado: “inscrito” para uma cliente, data final antes da inicial, valor por extenso diferente do número, nome escrito de dois jeitos.",
    tag: "IA",
  },
  {
    icon: FileSpreadsheet,
    title: "Centenas de uma vez",
    text: "Cole do Excel ou envie a planilha: um documento por linha, todos num ZIP, com relatório do que deu certo.",
  },
  {
    icon: Layers,
    title: "Kits de documentos",
    text: "Contrato + procuração + recibo com os mesmos dados do cliente, preenchidos uma vez só.",
  },
  {
    icon: Fingerprint,
    title: "Feito para o Brasil",
    text: "Valor e data por extenso automáticos. CPF, CNPJ, OAB e CEP validados antes de gerar.",
  },
  {
    icon: Type,
    title: "Sua formatação, intacta",
    text: "Cabeçalho, rodapé, tabelas, fontes e logotipo do seu documento continuam iguais. Saída em Word ou PDF.",
  },
  {
    icon: History,
    title: "Histórico de tudo",
    text: "Cada geração fica registrada: baixe de novo dentro do prazo ou repita um lote com um clique.",
  },
];

const SECURITY = [
  { icon: Lock, title: "Cada conta isolada", text: "Seus modelos e documentos só aparecem para quem entra na sua conta." },
  { icon: KeyRound, title: "Links que expiram", text: "Downloads usam links temporários; os arquivos gerados são apagados automaticamente depois do prazo." },
  { icon: Trash2, title: "Seus dados, sua decisão", text: "Peça a exportação completa ou a exclusão da conta e dos documentos quando quiser." },
  { icon: Sparkles, title: "IA sem treinar com você", text: "A IA recebe só o texto necessário, por provedores que não guardam nem treinam com os seus dados." },
];

const FAQ: { q: string; a: ReactNode }[] = [
  { q: "Preciso instalar alguma coisa?", a: "Não. O DocFeito funciona no navegador, no computador ou no celular. Você entra, envia um documento e já pode gerar." },
  {
    q: "Quais documentos posso usar?",
    a: "Word (.docx) e PDF digitado, aquele que sai do Word, do Google Docs ou de um sistema. PDF escaneado (foto do papel) não é aceito, porque o texto ali é uma imagem e os dados sairiam com erros.",
  },
  { q: "A IA pode errar?", a: "Pode, e por isso ela sugere e você confirma. Nenhum campo é criado sem você ver, e você confere o documento antes de gerar." },
  {
    q: "Meus documentos são usados para treinar IA?",
    a: "Não. Enviamos ao modelo de IA apenas o texto necessário para aquela tarefa, por provedores configurados para não guardar nem usar os dados em treinamento.",
  },
  { q: "Como funciona o pagamento?", a: "Assinatura mensal ou anual no cartão de crédito, ou pagamento por Pix. O plano Grátis não pede cartão." },
  { q: "Posso cancelar quando quiser?", a: "Sim, sem fidelidade e sem multa. Você cancela no próprio app e continua com acesso até o fim do período pago." },
  { q: "E se eu passar do limite do plano?", a: "Avisamos antes de chegar no limite. Você pode trocar de plano a qualquer momento, e a diferença é calculada proporcionalmente." },
  {
    q: "Os documentos gerados têm validade jurídica?",
    a: "O DocFeito preenche os seus próprios modelos, com o texto que você definiu. A validade depende desse conteúdo e da assinatura das partes. O DocFeito não presta orientação jurídica.",
  },
];

function Section({ id, eyebrow, title, sub, children, dark, className }: { id?: string; eyebrow?: string; title: ReactNode; sub?: ReactNode; children: ReactNode; dark?: boolean; className?: string }) {
  return (
    <section id={id} className={`scroll-mt-20 px-5 py-20 sm:py-28 ${dark ? "bg-ink text-white" : ""} ${className ?? ""}`}>
      <div className="mx-auto max-w-7xl">
        <div className="mx-auto mb-12 max-w-3xl text-center sm:mb-16">
          {eyebrow && <p className={`mb-3 text-sm font-bold uppercase tracking-[0.18em] ${dark ? "text-brand-bright" : "text-primary"}`}>{eyebrow}</p>}
          <h2 className="font-display text-3xl font-extrabold tracking-tight sm:text-5xl">{title}</h2>
          {sub && <p className={`mt-5 text-lg ${dark ? "text-zinc-400" : "text-zinc-600"}`}>{sub}</p>}
        </div>
        {children}
      </div>
    </section>
  );
}

function Cta({ children = "Começar grátis", testId }: { children?: ReactNode; testId?: string }) {
  return (
    <Link href="/register" data-testid={testId} className="group inline-flex items-center gap-2 rounded-full bg-highlight px-7 py-3.5 text-base font-bold text-ink shadow-xl shadow-highlight/20 transition hover:bg-[#ffe066]">
      {children} <ArrowRight className="h-4 w-4 transition group-hover:translate-x-0.5" aria-hidden />
    </Link>
  );
}

export default function Landing() {
  return (
    <div className={`site ${body.variable} bg-white font-[family-name:var(--site-body)] text-ink antialiased`}>
      <SiteHeader />
      <main id="main">
        {/* ------------------------------------------------------------------ topo */}
        <section className="site-hero relative overflow-hidden bg-ink px-5 pb-20 pt-32 text-white sm:pb-28 sm:pt-40">
          <div aria-hidden className="site-hero-glow pointer-events-none absolute inset-0" />
          <div className="relative mx-auto grid max-w-7xl items-center gap-14 lg:grid-cols-[1fr_1.15fr]">
            <div>
              <a href="#recursos" className="inline-flex items-center gap-2 rounded-full border border-brand-bright/30 bg-brand/10 px-3.5 py-1.5 text-sm font-medium text-brand-bright transition hover:bg-brand/20">
                <Sparkles className="h-4 w-4" aria-hidden /> Novo: a IA encontra os campos por você
              </a>
              <h1 className="mt-6 font-display text-[2.6rem] font-extrabold leading-[1.06] tracking-tight sm:text-6xl xl:text-[4.25rem]">
                Documento feito. <span className="site-chip">Sem copiar e colar.</span>
              </h1>
              <p className="mt-6 max-w-xl text-lg leading-relaxed text-zinc-300 sm:text-xl">
                Envie o contrato, a procuração ou o recibo que você já usa, em Word ou PDF. A IA marca nome, CPF, valores e datas. Você preenche um formulário e baixa{" "}
                <strong className="text-white">1 ou 1.000 documentos prontos</strong>, com a sua formatação.
              </p>
              <div className="mt-9 flex flex-wrap items-center gap-4">
                <Cta testId="hero-cta">Começar grátis</Cta>
                <a href="#demo" className="inline-flex items-center gap-2 rounded-full px-5 py-3.5 text-base font-semibold text-white ring-1 ring-white/20 transition hover:bg-white/10">
                  <Play className="h-4 w-4" aria-hidden /> Testar sem cadastro
                </a>
              </div>
              <ul className="mt-8 flex flex-wrap gap-x-6 gap-y-2 text-sm text-zinc-400">
                {["Grátis para começar", "Sem cartão de crédito", "Word e PDF"].map((t) => (
                  <li key={t} className="flex items-center gap-1.5">
                    <CheckCircle2 className="h-4 w-4 text-brand-bright" aria-hidden /> {t}
                  </li>
                ))}
              </ul>
            </div>
            <div className="relative">
              <div aria-hidden className="absolute -inset-6 rounded-[2rem] bg-brand/20 blur-3xl" />
              <div className="relative">
                <LiveDemo mode="auto" compact />
              </div>
            </div>
          </div>
        </section>

        {/* ------------------------------------------------------------------ para quem */}
        <section aria-label="Para quem é" className="border-b border-zinc-100 px-5 py-10">
          <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-center gap-x-8 gap-y-4">
            <p className="w-full text-center text-sm font-semibold text-zinc-500 lg:w-auto">Feito para quem vive de documentos:</p>
            {SEGMENTS.map((s) => (
              <span key={s.label} className="flex items-center gap-2 text-sm font-semibold text-zinc-700">
                <s.icon className="h-5 w-5 text-primary" aria-hidden /> {s.label}
              </span>
            ))}
          </div>
        </section>

        {/* ------------------------------------------------------------------ antes x depois */}
        <Section eyebrow="O problema" title="Chega de caçar nome e CPF no Word." sub="Todo documento repetido é tempo perdido e uma chance de errar. O DocFeito faz a parte chata.">
          <div className="grid gap-6 lg:grid-cols-2">
            <div className="rounded-2xl border border-zinc-200 bg-zinc-50 p-8">
              <p className="mb-6 font-display text-lg font-bold text-zinc-500">No Word · documento por documento</p>
              <ul className="space-y-4">
                {BEFORE.map((t) => (
                  <li key={t} className="flex gap-3 text-zinc-600">
                    <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-red-400" aria-hidden /> {t}
                  </li>
                ))}
              </ul>
            </div>
            <div className="rounded-2xl border border-brand/30 bg-gradient-to-br from-primary-soft to-white p-8 shadow-xl shadow-brand/10">
              <p className="mb-6 font-display text-lg font-bold text-primary">Com o DocFeito · em menos de 1 minuto</p>
              <ul className="space-y-4">
                {AFTER.map((t) => (
                  <li key={t} className="flex gap-3 font-medium text-zinc-800">
                    <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-brand" aria-hidden /> {t}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </Section>

        {/* ------------------------------------------------------------------ demonstração interativa */}
        <Section
          id="demo"
          eyebrow="Teste agora, sem cadastro"
          title={<>Veja a IA marcar os campos. Depois, mude o que quiser.</>}
          sub="Escolha um documento de exemplo, clique em “Encontrar os campos com IA” e preencha o formulário: o documento muda na hora, com o valor por extenso e o CPF conferido."
          className="bg-gradient-to-b from-paper to-white"
        >
          <div className="mx-auto max-w-6xl">
            <LiveDemo mode="interactive" />
          </div>
        </Section>

        {/* ------------------------------------------------------------------ como funciona */}
        <Section id="como-funciona" eyebrow="Como funciona" title="Do seu Word ao documento pronto em 3 passos.">
          <ol className="grid gap-8 lg:grid-cols-3">
            {STEPS.map((s, i) => (
              <li key={s.title} className="flex flex-col overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm">
                {hasImage(s.shot) && (
                  <div className="border-b border-zinc-100 bg-zinc-50">
                    <SiteImage name={s.shot} sizes="(min-width: 1024px) 400px, 100vw" />
                  </div>
                )}
                <div className="p-7">
                  <span className="flex items-center gap-3">
                    <span className="grid h-10 w-10 place-items-center rounded-full bg-highlight font-display text-base font-extrabold text-ink">{i + 1}</span>
                    <s.icon className="h-6 w-6 text-primary" aria-hidden />
                  </span>
                  <h3 className="mt-5 font-display text-xl font-bold">{s.title}</h3>
                  <p className="mt-2 text-zinc-600">{s.text}</p>
                </div>
              </li>
            ))}
          </ol>
        </Section>

        {/* ------------------------------------------------------------------ vídeo */}
        {demoVideo && (
          <Section dark eyebrow="O app de verdade" title="Veja o DocFeito em ação." sub="Do upload do contrato ao PDF pronto, sem cortes de mentira: esta é a tela que você vai usar.">
            <div className="mx-auto max-w-5xl overflow-hidden rounded-2xl ring-1 ring-white/10 shadow-2xl shadow-brand/20">
              <DemoVideo />
            </div>
          </Section>
        )}

        {/* ------------------------------------------------------------------ recursos */}
        <Section id="recursos" eyebrow="Recursos" title="Tudo o que faltava no seu Word." sub="Feito para o dia a dia de quem gera contratos, procurações, recibos e declarações.">
          <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f) => (
              <div
                key={f.title}
                className={`relative rounded-2xl border p-7 ${f.big ? "border-transparent bg-ink text-white md:col-span-2 lg:col-span-1 lg:row-span-2" : "border-zinc-200 bg-white"}`}
              >
                {f.tag && (
                  <span className={`absolute right-5 top-5 rounded-full px-2.5 py-0.5 text-xs font-bold ${f.big ? "bg-highlight text-ink" : "bg-highlight-soft text-ink"}`}>{f.tag}</span>
                )}
                <f.icon className={`h-8 w-8 ${f.big ? "text-brand-bright" : "text-primary"}`} aria-hidden />
                <h3 className={`mt-5 font-display font-bold ${f.big ? "text-2xl" : "text-lg"}`}>{f.title}</h3>
                <p className={`mt-2 ${f.big ? "text-zinc-300" : "text-zinc-600"}`}>{f.text}</p>
                {f.big && (
                  <div aria-hidden className="mt-8 space-y-2 font-serif text-sm leading-relaxed text-zinc-300">
                    <p>
                      Pelo presente instrumento, <span className="rounded bg-highlight px-1 font-sans font-semibold text-ink">Maria Aparecida Souza</span>, CPF{" "}
                      <span className="rounded bg-highlight px-1 font-sans font-semibold text-ink">529.982.247-25</span>, contrata os serviços pelo valor de{" "}
                      <span className="rounded bg-highlight px-1 font-sans font-semibold text-ink">R$ 4.500,00</span>…
                    </p>
                    <p className="flex flex-wrap gap-2 pt-3 font-sans text-xs">
                      {["Nome do cliente", "CPF", "Valor", "Data", "Endereço"].map((t) => (
                        <span key={t} className="rounded-full bg-white/10 px-2.5 py-1 text-zinc-200">{t}</span>
                      ))}
                    </p>
                  </div>
                )}
              </div>
            ))}
          </div>
        </Section>

        {/* ------------------------------------------------------------------ casos de uso (com imagens geradas) */}
        {(hasImage("seg-advocacia") || hasImage("seg-contabilidade")) && (
          <Section eyebrow="Na prática" title="Do escritório de advocacia à imobiliária." className="bg-paper">
            <div className="grid gap-6 md:grid-cols-2">
              {[
                { name: "seg-advocacia", title: "Advocacia", text: "Procurações, contratos de honorários e substabelecimentos com a qualificação do cliente preenchida em segundos." },
                { name: "seg-contabilidade", title: "Contabilidade", text: "Contratos de prestação de serviços e recibos para toda a carteira de clientes, gerados de uma planilha." },
                { name: "seg-imobiliaria", title: "Imobiliárias", text: "Contratos de locação, recibos de aluguel e vistorias com os dados do imóvel e das partes, sem redigitar." },
                { name: "seg-rh", title: "RH e Departamento Pessoal", text: "Contratos de trabalho, avisos de férias e declarações para cada colaborador, no padrão da empresa." },
              ]
                .filter((c) => hasImage(c.name))
                .map((c) => (
                  <figure key={c.name} className="overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm">
                    <SiteImage name={c.name} sizes="(min-width: 768px) 50vw, 100vw" className="aspect-[3/2] object-cover" />
                    <figcaption className="p-6">
                      <h3 className="font-display text-xl font-bold">{c.title}</h3>
                      <p className="mt-1 text-zinc-600">{c.text}</p>
                    </figcaption>
                  </figure>
                ))}
            </div>
          </Section>
        )}

        {/* ------------------------------------------------------------------ calculadora */}
        <Section eyebrow="Faça a conta" title="Quanto tempo você perde copiando e colando?" sub="Arraste e veja o que volta para o seu mês.">
          <div className="mx-auto max-w-5xl">
            <RoiCalculator />
          </div>
        </Section>

        {/* ------------------------------------------------------------------ segurança */}
        <Section dark eyebrow="Segurança" title="Seus documentos ficam com você." sub="Documento de cliente é coisa séria. O DocFeito foi construído com isso em mente desde o primeiro dia.">
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {SECURITY.map((s) => (
              <div key={s.title} className="rounded-2xl border border-white/10 bg-white/[0.03] p-6">
                <s.icon className="h-7 w-7 text-brand-bright" aria-hidden />
                <h3 className="mt-4 font-display text-lg font-bold">{s.title}</h3>
                <p className="mt-2 text-sm text-zinc-400">{s.text}</p>
              </div>
            ))}
          </div>
        </Section>

        {/* ------------------------------------------------------------------ preços */}
        <Section id="precos" eyebrow="Preços" title="Comece grátis. Assine quando fizer sentido." sub="Um plano para cada ritmo de trabalho. Troque ou cancele quando quiser.">
          <Pricing />
        </Section>

        {/* ------------------------------------------------------------------ perguntas */}
        <Section id="perguntas" eyebrow="Dúvidas" title="Perguntas frequentes" className="bg-paper">
          <div className="mx-auto max-w-3xl divide-y divide-zinc-200 rounded-2xl border border-zinc-200 bg-white">
            {FAQ.map((f) => (
              <details key={f.q} className="group px-6 py-5 [&_summary::-webkit-details-marker]:hidden">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-display text-lg font-bold text-zinc-900">
                  {f.q}
                  <span aria-hidden className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-zinc-100 text-xl text-zinc-500 transition group-open:rotate-45">+</span>
                </summary>
                <p className="mt-3 leading-relaxed text-zinc-600">{f.a}</p>
              </details>
            ))}
          </div>
        </Section>

        {/* ------------------------------------------------------------------ chamada final */}
        <section className="site-hero relative overflow-hidden bg-ink px-5 py-24 text-center text-white sm:py-32">
          <div aria-hidden className="site-hero-glow pointer-events-none absolute inset-0" />
          <div className="relative mx-auto max-w-3xl">
            <h2 className="font-display text-4xl font-extrabold tracking-tight sm:text-6xl">Seu próximo documento pode levar 30 segundos.</h2>
            <p className="mt-6 text-lg text-zinc-300">Crie sua conta grátis, envie um documento que você já usa e gere o primeiro hoje.</p>
            <div className="mt-10 flex flex-wrap justify-center gap-4">
              <Cta testId="final-cta">Começar grátis agora</Cta>
            </div>
            <p className="mt-5 text-sm text-zinc-500">Sem cartão de crédito · Cancele quando quiser</p>
          </div>
        </section>
      </main>

      <footer className="border-t border-zinc-200 px-5 py-10">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-6 text-sm text-zinc-500">
          <Logo />
          <span>Documento feito, sem copiar e colar.</span>
          <nav aria-label="Rodapé" className="ml-auto flex flex-wrap gap-5">
            <a href="#precos" className="hover:text-zinc-900">Preços</a>
            <Link href="/termos" className="hover:text-zinc-900">Termos de uso</Link>
            <Link href="/privacidade" className="hover:text-zinc-900">Privacidade</Link>
            <Link href="/login" className="hover:text-zinc-900">Entrar</Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}
