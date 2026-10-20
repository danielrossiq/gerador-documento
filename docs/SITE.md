# Landing pública (`/`)

Spec: `Shared/DanielRossi/docs/design/minuta-site/landing-spec.md` (v1) e `landing-spec-v2.md` (direção de arte e
mídia; substitui a v1 nesses pontos), do Product Design Lead.

- `/` mostra a landing para qualquer visitante (antes redirecionava para `/dashboard`). Não há guarda de sessão
  nessa rota, então não existe loop com a guarda do app: quem já está logado segue por **Entrar** ou acessa `/dashboard`.
- CTAs: **Entrar** → `/login`, **Criar conta** → `/register`.
- Copy limitada ao que o produto faz hoje. Não afirmar preço, disponibilidade comercial, LGPD, IA, importação de PDF
  nem aconselhamento jurídico (o E2E `e2e/landing.spec.ts` verifica alguns desses termos).
- Código: `frontend/src/app/page.tsx`, `frontend/src/components/landing/*`, estilos `.landing`/`.lp-*` em `globals.css`
  (escopados; o app autenticado não muda). Fontes Space Grotesk e DM Sans via `next/font` (baixadas no build).

## Imagens e vídeo (OpenRouter)

`scripts/generate_site_media.py` gera os assets listados em `scripts/site_media.json` pela API da OpenRouter
(`POST /api/v1/images`; vídeo assíncrono em `POST /api/v1/videos` → polling → `GET /api/v1/videos/{id}/content`),
baixa o resultado na hora e grava tudo em `frontend/public/site/`, servido pelo próprio site (sem hotlink).

```bash
python scripts/generate_site_media.py --dry-run        # plano, limites, preços ao vivo e custo; sem chave
python scripts/generate_site_media.py                  # gera só os assets ausentes
python scripts/generate_site_media.py --redo <slug>    # descarta um asset reprovado e gera de novo (conta no orçamento)
python scripts/generate_site_media.py --optimize-only  # refaz variantes a partir dos originais
python -m unittest discover -s scripts/tests           # testes do gerador (sem rede; o de vídeo exige ffmpeg)
```

- **Plano:** `scripts/site_media.json` é cópia de `minuta-site/site_media.v2.json` (landing-spec-v2): 7 imagens e 1
  vídeo, todas decorativas (`alt=""`).
- **Modelos e limites (allowlist no código, landing-spec-v2 §10):** `black-forest-labs/flux-3-image` 2K, até 9
  chamadas (US$ 0,10 por imagem); `google/gemini-nano-banana-2.1` 1K para as edições com referência, até 3 chamadas;
  `google/veo-3.1-fast` 1080p sem áudio, até 2 chamadas (US$ 0,10/s × 8 s), **sem fallback**. Loop: a mesma imagem vai
  como `first_frame` e `last_frame`, e o último quadro (repetido) é cortado na codificação. O vídeo recebe `seed`
  (registrado no manifest); as APIs de imagem desses modelos não aceitam seed.
- **Chave:** lida apenas do arquivo `~/.minuta/openrouter.key` (ou do caminho em `OPENROUTER_KEY_FILE`), fora do
  repositório, e validada antes do uso (uma linha, prefixo `sk-or-`, até 1 KB). Nunca vai para argumentos, logs,
  manifest ou mensagens de erro; só é enviada a `https://openrouter.ai/api/v1/`.
- **Rede e arquivos:** só `https://openrouter.ai` (allowlist fixa) e nenhum redirect é seguido. JSON exige
  `application/json` e tem teto de tamanho; o vídeo é baixado em streaming para um `.part` e só é movido depois de
  conferidos Content-Type `video/mp4`, tamanho e assinatura. As URLs assinadas (`urls`) não são usadas nem gravadas.
  Slugs `^[a-z0-9][a-z0-9-]{0,39}$`, e todo caminho gravado precisa ficar dentro de `frontend/public/site/` ou de
  `scripts/.media-originals/`.
- **Concorrência e idempotência:** uma execução por vez (`scripts/.site_media.lock`). Asset pronto não é gerado de
  novo; job de vídeo é retomado pelo id (inclusive se o download falhar); chamada que caiu sem resultado conhecido
  só é paga de novo com `--retry-unknown <slug>`.
- **Orçamento: teto de US$ 3,00** (dos US$ 5 de saldo, US$ 2 ficam para a avaliação da IA), contando falhas.
  Antes de **cada** chamada paga:
  1. o custo máximo dela é conferido ao vivo nos endpoints públicos (preço fixo por imagem na resolução pedida, mais
     cobranças por imagem de referência; ou preço por segundo do SKU pedido × duração). Unidade de cobrança sem
     máximo conhecido, item de cobrança desconhecido ou preço acima do aprovado: nada sai. Na imagem, o pedido vai
     com `provider.only` (os provedores conferidos) e `allow_fallbacks: false`;
  2. o uso real da chave é medido (`GET /key`). Para a execução: gasto da chave não explicado pelo manifest, limite
     de crédito menor que o máximo da chamada ou falha dessa medida;
  3. gasto registrado (ou medido na chave, o que for maior) + máximo da chamada não pode passar de US$ 3,00.
  A chamada é gravada com a reserva antes de sair; custo informado pela API acima da reserva encerra a execução.
- **Modelo cobrado por token (Nano Banana):** não tem custo máximo verificável antes do envio. Só roda se a chave
  tiver **limite de crédito na OpenRouter** de no máximo o que resta do orçamento (ex.: chave só do site com limite
  de US$ 3,00); sem isso, as edições I2/I4 são puladas e o resto segue.
- **Saídas:** imagens AVIF/WebP responsivas sem metadados; vídeo MP4 H.264 + WebM VP9 sem trilha de áudio e sem
  metadados (alvo de 2,5 MB no hero), com pôster AVIF/WebP do primeiro quadro.
- **Falha fechada:** imagem que não abre, truncada ou acima de 4096 px é recusada. O vídeo original precisa
  ter codec conhecido, até 8,5 s, até 1920×1080 e no máximo 60 quadros/s; a saída precisa ter até 8,1 s, a largura
  pedida, nenhum áudio e até 110% do alvo de bytes. Fora disso, nada vai para `public/site/` (o original pago fica
  guardado para `--optimize-only`). ffmpeg/ffprobe têm limite de 15 min.
- **Registros:** `scripts/site_media.manifest.json` (prompt, modelo, parâmetros, ids, custo, data e checagens) fica fora
  de `public/`. A landing importa só `frontend/src/components/landing/site-media.json` (arquivos, dimensões e alt).
- Originais em `scripts/.media-originals/` (ignorado pelo git). Requer Pillow com AVIF e ffmpeg/ffprobe no PATH
  (ou `FFMPEG`/`FFPROBE`).
- Sem asset no `site-media.json`, a landing renderiza só o texto.
