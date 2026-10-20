# Landing pública (`/`)

Spec: `Shared/DanielRossi/docs/design/minuta-site/landing-spec.md` (Product Design Lead).

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

- **Modelos (allowlist no código):** imagens `black-forest-labs/flux-3-image` em 2K (US$ 0,10) e
  `google/gemini-nano-banana-2.1` para edição/variação com referência (cobrado por token; estimado em US$ 0,10);
  vídeo `google/veo-3.1-fast` 1080p sem áudio (US$ 0,10/s, 4/6/8 s), com fallback `google/veo-3.1-lite` (US$ 0,05/s).
  Loop: a mesma imagem vai como `first_frame` e `last_frame`, e o último quadro (repetido) é cortado na codificação.
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
- **Orçamento:** US$ 3,00 no total (dos US$ 5 de saldo, US$ 2 ficam para a avaliação da IA); imagens até 12
  chamadas e 8 finais; vídeo até 4 chamadas, 2 finais e 8 s.
  Cada chamada é gravada antes de sair e falhas contam. Sem custo devolvido pela API, vale a estimativa. Antes de
  gastar, os preços ao vivo são conferidos; acima do aprovado, nada é gerado. Job de vídeo interrompido é retomado
  pelo id, sem pagar outro.
- **Saídas:** imagens AVIF/WebP responsivas sem metadados; vídeo MP4 H.264 + WebM VP9 sem trilha de áudio e sem
  metadados (alvo ~3 MB no hero), com pôster AVIF/WebP do primeiro quadro.
- **Falha fechada:** imagem que não abre, truncada ou acima de 4096 px é recusada. O vídeo original precisa
  ter codec conhecido, até 8,5 s, até 1920×1080 e no máximo 60 quadros/s; a saída precisa ter até 8,1 s, a largura
  pedida, nenhum áudio e até 110% do alvo de bytes. Fora disso, nada vai para `public/site/` (o original pago fica
  guardado para `--optimize-only`). ffmpeg/ffprobe têm limite de 15 min.
- **Registros:** `scripts/site_media.manifest.json` (prompt, modelo, parâmetros, ids, custo, data e checagens) fica fora
  de `public/`. A landing importa só `frontend/src/components/landing/site-media.json` (arquivos, dimensões e alt).
- Originais em `scripts/.media-originals/` (ignorado pelo git). Requer Pillow com AVIF e ffmpeg/ffprobe no PATH
  (ou `FFMPEG`/`FFPROBE`).
- Sem asset no `site-media.json`, a landing renderiza só o texto.
