// Manual de identidade visual do DocFeito → docs/marca/DocFeito-Identidade-Visual.pdf (A4 paisagem).
// Usa os vetores de frontend/public/brand e as fontes da marca (sem nada externo). Uso (de dentro de frontend/):
//   node ../scripts/brand_book.cjs            (gera o PDF e prévias PNG das páginas em scripts/.media-originals/brand/book)
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(require.resolve("playwright", { paths: [process.cwd()] }));

const ROOT = path.resolve(__dirname, "..");
const BRAND = path.join(ROOT, "frontend", "public", "brand");
const FONTS = path.join(__dirname, ".media-originals", "brand");
const OUT_PDF = path.join(ROOT, "docs", "marca", "DocFeito-Identidade-Visual.pdf");
const PREVIEW = path.join(FONTS, "book");

const svg = (f) => fs.readFileSync(path.join(BRAND, f), "utf-8").replace(/ width="[\d.]+" height="[\d.]+"/, "");
const font = (f) => fs.readFileSync(path.join(FONTS, f)).toString("base64");
const P = JSON.parse(fs.readFileSync(path.join(BRAND, "paleta.json"), "utf-8"));

const COLORS = [
  ["Tinta", P.tinta, "Textos, a folha do ícone, fundos escuros. É a base: segura e séria.", "#fff"],
  ["Verde Feito", P.verde, "A cor da marca: o check, a dobra e o “Feito”. Use em destaque, nunca em texto pequeno.", "#0E1A2B"],
  ["Verde Ação", P.verde_escuro, "Botões e links do produto. Contraste 5,3:1 com texto branco (WCAG AA).", "#fff"],
  ["Marca-texto", P.marca_texto, "O destaque dos campos e as chamadas principais. É o “aqui muda” do documento.", "#0E1A2B"],
  ["Verde claro", P.verde_claro, "Fundos de confirmação e estados “feito”.", "#0E1A2B"],
  ["Marca-texto claro", P.marca_texto_claro, "Fundo de campo a preencher, avisos leves.", "#0E1A2B"],
  ["Papel", P.papel, "Fundo das páginas: quente, de papel, menos frio que o branco puro.", "#0E1A2B"],
];
const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)).join(" · ");

const page = (cls, body) => `<section class="page ${cls}">${body}<footer><span>DocFeito · Identidade visual</span><span class="n"></span></footer></section>`;

const html = `<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>DocFeito — Identidade visual</title><style>
@font-face{font-family:"Jakarta";src:url(data:font/woff2;base64,${font("PlusJakartaSans-latin.woff2")}) format("woff2");font-weight:200 800}
@font-face{font-family:"Inter";src:url(data:font/woff2;base64,${font("Inter-latin.woff2")}) format("woff2");font-weight:100 900}
@page{size:A4 landscape;margin:0}
*{box-sizing:border-box}html,body{margin:0;-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{font-family:Inter,system-ui,sans-serif;color:${P.tinta};counter-reset:pg}
.page{width:297mm;height:210mm;padding:18mm 20mm 16mm;position:relative;overflow:hidden;page-break-after:always;background:${P.papel};counter-increment:pg}
.page:last-child{page-break-after:auto}
footer{position:absolute;left:20mm;right:20mm;bottom:9mm;display:flex;justify-content:space-between;font-size:8.5pt;color:#7a8494}
footer .n::after{content:counter(pg,decimal-leading-zero)}
.dark{background:${P.tinta};color:#fff}.dark footer{color:#8fa0b8}
h1,h2,h3{font-family:Jakarta;letter-spacing:-.02em;margin:0}
h2{font-size:30pt;font-weight:800;line-height:1.05}
h3{font-size:13pt;font-weight:800;margin-bottom:2mm}
.eyebrow{font:800 9pt Jakarta;letter-spacing:.18em;text-transform:uppercase;color:${P.verde_escuro};margin-bottom:4mm}
.dark .eyebrow{color:${P.verde_neon}}
p{font-size:11pt;line-height:1.55;margin:0 0 3mm}
.lead{font-size:14pt;line-height:1.5;max-width:200mm;color:#3b4656}.dark .lead{color:#c9d3e0}
.mark{background:linear-gradient(transparent 14%,${P.marca_texto} 14%,${P.marca_texto} 90%,transparent 90%);padding:0 .1em;color:${P.tinta}}
.grid{display:grid;gap:7mm}.g2{grid-template-columns:1fr 1fr}.g3{grid-template-columns:repeat(3,1fr)}.g4{grid-template-columns:repeat(4,1fr)}
.card{background:#fff;border:1px solid #e4e1d8;border-radius:5mm;padding:7mm}
.tile{border-radius:5mm;padding:8mm;display:grid;place-items:center;min-height:52mm}
.tile svg{max-width:100%;max-height:34mm}.free svg{max-height:none}.mini{padding:5mm}.mini svg{max-height:20mm}
.cap{font-size:9pt;color:#5d6878;margin-top:2.5mm}
.swatch{border-radius:4mm;overflow:hidden;border:1px solid #0001;background:#fff}
.swatch .c{height:30mm;padding:4mm;font:800 11pt Jakarta;display:flex;align-items:flex-end}
.swatch .t{padding:3.5mm 4mm;font-size:8.5pt;line-height:1.45;color:#3b4656}
.swatch code{font:600 9pt Inter;color:${P.tinta}}
.do,.dont{font-size:10pt;padding:3mm 4mm;border-radius:3mm}
.do{background:${P.verde_claro}}.dont{background:#fdeaea}
.btn{display:inline-block;font:700 11pt Inter;border-radius:99px;padding:3mm 7mm}
ul{margin:0;padding-left:5mm}li{font-size:10.5pt;line-height:1.55;margin-bottom:1.5mm}
.big{font:800 54pt/1 Jakarta;letter-spacing:-.03em}
</style><body>
${page("dark", `
  <div style="height:100%;display:flex;flex-direction:column;justify-content:center;gap:10mm">
    <div style="width:150mm">${svg("docfeito-logo-negativo.svg")}</div>
    <h1 style="font-size:40pt;font-weight:800;line-height:1.05;max-width:220mm">Documento feito. <span class="mark">Sem copiar e colar.</span></h1>
    <p class="lead">Manual de identidade visual · versão 1 · outubro de 2026</p>
  </div>`)}
${page("", `
  <p class="eyebrow">A marca</p>
  <h2>O que é o DocFeito</h2>
  <div class="grid g2" style="margin-top:10mm;align-items:start">
    <div>
      <p class="lead">O DocFeito transforma os documentos que um escritório já usa — contratos, procurações, recibos — em formulários. A IA marca o que muda; a pessoa preenche uma vez e gera 1 ou 1.000 documentos prontos, com a formatação dela.</p>
      <p style="margin-top:6mm">O nome diz a promessa: o documento <b>feito</b>, sem retrabalho. A marca é prática e confiável, como um bom colega de escritório que resolve — nada de jargão de tecnologia.</p>
    </div>
    <div class="card">
      <h3>Personalidade</h3>
      <ul>
        <li><b>Prática:</b> mostra o resultado, não a tecnologia.</li>
        <li><b>Confiável:</b> documento de cliente é coisa séria.</li>
        <li><b>Brasileira:</b> CPF, valor por extenso, Pix — fala a língua do escritório.</li>
        <li><b>Leve:</b> tira o peso do trabalho repetitivo; um toque de humor, nunca piada.</li>
      </ul>
      <h3 style="margin-top:6mm">Assinatura</h3>
      <p style="font:800 16pt Jakarta">Documento feito. <span class="mark">Sem copiar e colar.</span></p>
    </div>
  </div>`)}
${page("", `
  <p class="eyebrow">O símbolo</p>
  <h2>Uma folha, a dobra e o check</h2>
  <div class="grid g2" style="margin-top:10mm;align-items:center">
    <div class="tile free" style="background:#fff;min-height:110mm;border:1px solid #e4e1d8">
      <div style="width:80mm">${svg("docfeito-icone.svg")}</div>
    </div>
    <div>
      <p class="lead">Três ideias num desenho só:</p>
      <ul style="margin-top:4mm">
        <li><b>A folha</b> em tinta: o documento que a pessoa já tem.</li>
        <li><b>A dobra verde</b> no canto: o documento “virando” modelo — a página que vira.</li>
        <li><b>O check</b> que sobe até a dobra: feito. Ele recorta a folha, então o símbolo funciona sobre fundo claro, escuro ou foto.</li>
      </ul>
      <p style="margin-top:6mm">Desenhado numa grade de 64 unidades (folha 40 × 52, cantos com raio 8, traço do check 7,5). A geometria fica em <code>scripts/brand_build.py</code>: qualquer ajuste regenera todo o kit.</p>
    </div>
  </div>`)}
${page("", `
  <p class="eyebrow">Versões</p>
  <h2>Logo e ícone</h2>
  <div class="grid g3" style="margin-top:9mm">
    <div><div class="tile" style="background:#fff;border:1px solid #e4e1d8">${svg("docfeito-logo.svg")}</div><p class="cap"><b>Principal</b> — horizontal, sobre fundos claros.</p></div>
    <div><div class="tile" style="background:${P.tinta}">${svg("docfeito-logo-negativo.svg")}</div><p class="cap"><b>Negativo</b> — sobre tinta ou fotos escuras.</p></div>
    <div><div class="tile" style="background:#fff;border:1px solid #e4e1d8">${svg("docfeito-logo-vertical.svg")}</div><p class="cap"><b>Vertical</b> — espaços quadrados, capas, redes sociais.</p></div>
    <div><div class="tile" style="background:#fff;border:1px solid #e4e1d8"><div style="width:30mm">${svg("docfeito-icone.svg")}</div></div><p class="cap"><b>Ícone</b> — favicon, avatar, carimbo pequeno.</p></div>
    <div><div class="tile" style="background:${P.papel};border:1px solid #e4e1d8"><div style="width:30mm">${svg("docfeito-icone-app.svg")}</div></div><p class="cap"><b>Ícone de app</b> — celular, aba do navegador, atalhos.</p></div>
    <div><div class="tile" style="background:#fff;border:1px solid #e4e1d8;gap:4mm">${svg("docfeito-logo-mono-tinta.svg")}</div><p class="cap"><b>Monocromático</b> — carimbo, impressão em uma cor, fax.</p></div>
  </div>`)}
${page("", `
  <p class="eyebrow">Respiro e tamanho mínimo</p>
  <h2>Dê espaço para a marca</h2>
  <div class="grid g2" style="margin-top:10mm;align-items:center">
    <div class="tile" style="background:#fff;border:1px dashed #b9c2cf;min-height:80mm;padding:16mm">
      <div style="outline:2px dashed ${P.verde};outline-offset:9mm;width:150mm">${svg("docfeito-logo.svg")}</div>
    </div>
    <div>
      <ul>
        <li><b>Respiro:</b> ao redor do logo, no mínimo a altura da dobra verde (¼ da altura do ícone). Nada de texto, borda ou outro logo dentro dessa área.</li>
        <li><b>Mínimo:</b> logo horizontal com 96 px (ou 25 mm) de largura; abaixo disso, use só o ícone.</li>
        <li><b>Ícone:</b> legível a partir de 16 px (favicon).</li>
        <li><b>Arquivos:</b> <code>frontend/public/brand</code> — SVG para tudo que for digital e impressão; PNG transparente de 16 a 2048 px.</li>
      </ul>
    </div>
  </div>`)}
${page("", `
  <p class="eyebrow">Cores</p>
  <h2>Tinta, verde e marca-texto</h2>
  <div class="grid g4" style="margin-top:8mm;gap:5mm">
    ${COLORS.map(([n, hex, use, fg]) => `<div class="swatch"><div class="c" style="background:${hex};color:${fg}">${n}</div><div class="t"><code>${hex.toUpperCase()}</code> · RGB ${rgb(hex)}<br>${use}</div></div>`).join("")}
    <div class="swatch" style="display:flex;flex-direction:column;justify-content:center;padding:5mm;background:#fff"><p style="font-size:9.5pt;margin:0"><b>Proporção:</b> muito papel e branco, tinta para texto, verde em pontos de “feito”, marca-texto só onde algo muda ou onde a pessoa deve clicar.</p></div>
  </div>`)}
${page("", `
  <p class="eyebrow">Tipografia</p>
  <h2>Plus Jakarta Sans e Inter</h2>
  <div class="grid g2" style="margin-top:10mm">
    <div class="card">
      <p class="cap" style="margin:0 0 3mm">Títulos e marca · Plus Jakarta Sans ExtraBold (800)</p>
      <div class="big">Aa Feito</div>
      <p style="font:800 22pt/1.15 Jakarta;margin-top:6mm;letter-spacing:-.02em">Seu próximo contrato em 30 segundos.</p>
      <p class="cap">Gratuita (Google Fonts, licença OFL). Espaçamento levemente fechado (−2%).</p>
    </div>
    <div class="card">
      <p class="cap" style="margin:0 0 3mm">Textos e interface · Inter</p>
      <div class="big" style="font-family:Inter;font-weight:600">Aa 123</div>
      <p style="margin-top:6mm">Envie o contrato que você já usa. A IA marca nome, CPF, valores e datas; você confere e gera em Word ou PDF.</p>
      <p class="cap">Gratuita (licença OFL). Regular para texto, Semibold para botões e rótulos. Números tabulares em tabelas e valores.</p>
    </div>
  </div>`)}
${page("", `
  <p class="eyebrow">Elementos</p>
  <h2>O marca-texto é a assinatura visual</h2>
  <div class="grid g2" style="margin-top:9mm;align-items:start">
    <div class="card" style="font-family:Georgia,serif;font-size:12.5pt;line-height:1.9">
      CONTRATANTE: <span class="mark">Marina Duarte Campos</span>, inscrita no CPF sob o nº <span class="mark">529.982.247-25</span>, pagará o valor mensal de <span class="mark">R$ 3.200,00</span> (três mil e duzentos reais), a partir de <span class="mark">10 de novembro de 2026</span>.
      <p class="cap" style="font-family:Inter;margin-top:4mm">No produto e na comunicação, o amarelo marca-texto mostra <b>o que muda</b> no documento — é o gesto que todo mundo já faz no papel.</p>
    </div>
    <div>
      <h3>Botões</h3>
      <p><span class="btn" style="background:${P.marca_texto};color:${P.tinta}">Começar grátis →</span> &nbsp; <span class="btn" style="background:${P.verde_escuro};color:#fff">Gerar documento</span> &nbsp; <span class="btn" style="border:1.5px solid #c9c4b7">Cancelar</span></p>
      <p class="cap">Amarelo: a chamada principal de marketing (uma por tela). Verde Ação: a ação principal dentro do produto.</p>
      <h3 style="margin-top:7mm">Estados</h3>
      <p><span class="btn" style="background:${P.verde_claro};color:${P.verde_escuro};font-size:9.5pt">✓ Feito · 12 documentos</span> &nbsp; <span class="btn" style="background:${P.marca_texto_claro};color:${P.tinta};font-size:9.5pt">3 campos para conferir</span></p>
    </div>
  </div>`)}
${page("", `
  <p class="eyebrow">Voz e tom</p>
  <h2>Fale como quem resolve</h2>
  <div class="grid g2" style="margin-top:9mm">
    <div>
      <ul>
        <li><b>Frases curtas</b>, com verbo de ação: “Envie”, “Confira”, “Gere”.</li>
        <li><b>O resultado primeiro</b>: “1.000 contratos em 2 minutos”, não “processamento em lote escalável”.</li>
        <li><b>Palavras do escritório</b>: contrato, procuração, CPF, valor por extenso — nada de “templates dinâmicos”.</li>
        <li><b>Honesta sobre a IA</b>: ela sugere, a pessoa confere. Nunca prometer “sem erros”.</li>
      </ul>
    </div>
    <div class="grid" style="gap:3mm">
      <div class="do"><b>Sim:</b> “Cole a mensagem do cliente: a IA coloca cada dado no campo certo.”</div>
      <div class="dont"><b>Não:</b> “Nossa IA de última geração revoluciona sua produtividade documental.”</div>
      <div class="do"><b>Sim:</b> “Esse CPF não confere. Corrija e gere de novo.”</div>
      <div class="dont"><b>Não:</b> “Erro 422: validação falhou.”</div>
      <div class="do"><b>Sim:</b> “Documento feito.”</div>
    </div>
  </div>`)}
${page("", `
  <p class="eyebrow">Usos incorretos</p>
  <h2>O que não fazer com a marca</h2>
  <div class="grid g4" style="margin-top:9mm;gap:5mm">
    ${[
      ["transform:scaleX(1.4)", "Distorcer ou esticar"],
      ["filter:hue-rotate(160deg)", "Trocar as cores"],
      ["transform:rotate(-12deg)", "Girar ou inclinar"],
      ["filter:drop-shadow(3px 3px 0 #f0f)", "Aplicar sombras e efeitos"],
    ].map(([st, t]) => `<div><div class="tile mini" style="background:#fff;border:1px solid #e4e1d8;min-height:42mm"><div style="width:44mm;${st}">${svg("docfeito-logo.svg")}</div></div><p class="cap">✕ ${t}</p></div>`).join("")}
    <div><div class="tile mini" style="background:repeating-linear-gradient(45deg,#ffd43b 0 10px,#12b886 10px 20px);min-height:42mm"><div style="width:44mm">${svg("docfeito-logo.svg")}</div></div><p class="cap">✕ Fundo poluído ou sem contraste</p></div>
    <div><div class="tile" style="background:#fff;border:1px solid #e4e1d8;min-height:42mm"><span style="font:800 22pt Jakarta;color:${P.tinta}">Doc<span style="color:${P.verde}">feito</span></span></div><p class="cap">✕ Reescrever o nome (é “DocFeito”, com D e F maiúsculos)</p></div>
    <div><div class="tile mini" style="background:#fff;border:1px solid #e4e1d8;min-height:42mm"><div style="width:44mm;outline:3px solid ${P.tinta};outline-offset:3mm">${svg("docfeito-logo.svg")}</div></div><p class="cap">✕ Colocar moldura ou contorno</p></div>
    <div><div class="tile" style="background:#fff;border:1px solid #e4e1d8;min-height:42mm;font:800 13pt Jakarta;color:${P.verde}">DOC ✓ FEITO</div><p class="cap">✕ Recriar o logo com outra fonte ou emoji</p></div>
  </div>`)}
${page("dark", `
  <p class="eyebrow">Aplicações</p>
  <h2>A marca no dia a dia</h2>
  <div class="grid g3" style="margin-top:10mm;align-items:center">
    <div class="tile" style="background:#162236"><div style="display:flex;gap:6mm;align-items:center">${[180, 120, 64].map((w) => `<div style="width:${w / 4}mm">${svg("docfeito-icone-app.svg")}</div>`).join("")}</div></div>
    <div class="tile" style="background:#fff;color:${P.tinta};padding:0;overflow:hidden;align-items:stretch">
      <div style="display:flex;align-items:center;justify-content:space-between;padding:5mm 6mm;border-bottom:1px solid #eee"><div style="width:30mm">${svg("docfeito-logo.svg")}</div><span class="btn" style="background:${P.marca_texto};font-size:7pt;padding:1.5mm 3mm">Começar grátis</span></div>
      <div style="padding:5mm 6mm;font:800 11.5pt/1.25 Jakarta">Documento feito. <span class="mark">Sem copiar e colar.</span></div>
    </div>
    <div class="tile" style="background:${P.marca_texto};color:${P.tinta};text-align:center"><div><div style="width:24mm;margin:0 auto 4mm">${svg("docfeito-icone.svg")}</div><div style="font:800 15pt Jakarta">Feito. ✓</div><div style="font-size:9pt;margin-top:1mm">Post de rede social</div></div></div>
  </div>
  <p class="lead" style="margin-top:10mm">Ícone de app, cabeçalho do site e post: a mesma folha com o check, o mesmo marca-texto. Arquivos prontos em <code style="color:#fff">frontend/public/brand</code>.</p>`)}
</body></html>`;

(async () => {
  fs.mkdirSync(path.dirname(OUT_PDF), { recursive: true });
  fs.mkdirSync(PREVIEW, { recursive: true });
  const browser = await chromium.launch({ channel: "msedge" });
  const pg = await browser.newPage({ viewport: { width: 1123, height: 794 } });
  await pg.setContent(html, { waitUntil: "load" });
  await pg.evaluate(() => document.fonts.ready);
  await pg.pdf({ path: OUT_PDF, width: "297mm", height: "210mm", printBackground: true, preferCSSPageSize: true });
  const n = await pg.locator("section.page").count();
  for (let i = 0; i < n; i++) await pg.locator("section.page").nth(i).screenshot({ path: path.join(PREVIEW, `p${String(i + 1).padStart(2, "0")}.png`) });
  await browser.close();
  console.log(OUT_PDF, `${(fs.statSync(OUT_PDF).size / 1e6).toFixed(2)} MB`, n, "páginas");
})();
