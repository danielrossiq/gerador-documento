# Marca DocFeito

O produto se chamava **Minuta**. Como o domínio minuta.com.br não estava disponível, virou **DocFeito**
(docfeito.com.br estava livre no Registro.br em 24/10/2026). O manual completo está em
[marca/DocFeito-Identidade-Visual.pdf](marca/DocFeito-Identidade-Visual.pdf).

## Resumo

- **Assinatura:** "Documento feito. Sem copiar e colar."
- **Símbolo:** a folha de documento em tinta, com o canto dobrado em verde e um check subindo para a dobra
  (documento + feito). O check recorta a folha por máscara, então o símbolo funciona sobre qualquer fundo e é
  legível a partir de 16 px.
- **Nome:** "Doc" em tinta e "Feito" em verde, na Plus Jakarta Sans ExtraBold, em contornos. Sempre "DocFeito",
  com D e F maiúsculos.
- **Cores:**

  | Cor | Hex | Uso |
  |---|---|---|
  | Tinta | `#0E1A2B` | Texto, a folha, fundos escuros |
  | Verde Feito | `#12B886` | Marca: check, dobra, "Feito" |
  | Verde Ação | `#0B7A5A` | Botões e links do app (AA com branco) |
  | Marca-texto | `#FFD43B` | Campos destacados e chamadas principais |
  | Papel | `#FAF8F3` | Fundo |

- **Tipografia:** Plus Jakarta Sans (títulos e marca) e Inter (texto). As duas são gratuitas (OFL).
- **Assinatura visual:** o **marca-texto amarelo** mostra o que muda no documento. Na landing e no app, campo a
  conferir é amarelo e campo pronto ou preenchido é verde.

## Arquivos e como regenerar

| O quê | Onde | Como gerar |
|---|---|---|
| SVGs: logo, ícone, app, negativo, mono, vertical | `frontend/public/brand/*.svg` | `python scripts/brand_build.py --font <PlusJakartaSans.woff2>` |
| PNGs transparentes de 16 a 2048 px | `frontend/public/brand/png/` | `node ../scripts/brand_export.cjs` (de dentro de `frontend/`) |
| Favicon e ícone Apple | `frontend/public/favicon.{svg,ico}`, `apple-touch-icon.png` | gerados junto com os PNGs |
| Manual em PDF | `docs/marca/DocFeito-Identidade-Visual.pdf` | `node ../scripts/brand_book.cjs` |
| Imagem de compartilhamento | `frontend/public/site/og-1200.webp` | `node ../scripts/site_og.cjs` |
| Estudos de conceito (Recraft) | `scripts/.media-originals/brand/` (fora do Git) | `python scripts/brand_gen.py` (orçamento de US$ 5) |

As fontes usadas pelos scripts (`PlusJakartaSans-latin.woff2` e `Inter-latin.woff2`) ficam em
`scripts/.media-originals/brand/`, fora do Git. Elas saem do build do site em `.next/static/media`.

## O que continua com o nome antigo, de propósito

Identificadores técnicos que o usuário não vê:

- o cookie `minuta_csrf`;
- as chaves `minuta:` do armazenamento do navegador;
- o projeto `minuta` do Docker e o banco `minuta`;
- a pasta `~/.minuta` das chaves;
- o pacote `minuta_backend`;
- a metadata `minuta_plan` na Stripe.

Renomear o cookie e as chaves deslogaria todo mundo e apagaria rascunhos. Os outros renomes exigiriam migrar dados
sem ganho para o cliente. Ver D36.
