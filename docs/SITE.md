# Landing pública (`/`)

Spec: `Shared/DanielRossi/docs/design/minuta-site/landing-spec.md` (Product Design Lead).

- `/` mostra a landing para qualquer visitante (antes redirecionava para `/dashboard`). Não há guarda de sessão
  nessa rota, então não existe loop com a guarda do app: quem já está logado segue por **Entrar** ou acessa `/dashboard`.
- CTAs: **Entrar** → `/login`, **Criar conta** → `/register`.
- Copy limitada ao que o produto faz hoje. Não afirmar preço, disponibilidade comercial, LGPD, IA, importação de PDF
  nem aconselhamento jurídico (o E2E `e2e/landing.spec.ts` verifica alguns desses termos).
- Código: `frontend/src/app/page.tsx`, `frontend/src/components/landing/*`, estilos `.landing`/`.lp-*` em `globals.css`
  (escopados; o app autenticado não muda). Fontes Space Grotesk e DM Sans via `next/font` (baixadas no build).

## Imagens (Runway)

`scripts/generate_site_images.py` gera as imagens listadas em `scripts/site_images.json` com `gen4_image`
(`POST /v1/text_to_image`, `X-Runway-Version: 2024-11-06`), faz polling de `GET /v1/tasks/{id}`, baixa o resultado na
hora (as URLs expiram) e grava AVIF/WebP em larguras responsivas em `frontend/public/site/`.

```bash
python scripts/generate_site_images.py --dry-run   # plano e custo, sem chamar a API
python scripts/generate_site_images.py             # gera só as imagens ausentes
python scripts/generate_site_images.py --optimize-only
```

- **Chave:** lida apenas do arquivo `~/.minuta/runway.key` (ou do caminho em `RUNWAY_KEY_FILE`), fora do repositório.
  Nunca vai para argumentos, logs, manifest ou mensagens de erro.
- **Orçamento:** máximo de 8 chamadas e 6 imagens, contado em `frontend/public/site/manifest.json`. Reexecuções não
  passam do limite, e uma chamada que falha também conta. Custo do `gen4_image`: 5 créditos em 720p, 8 em 1080p
  (US$ 0,01 por crédito). O script recusa proporções acima de 10 créditos.
- **Manifest:** prompt, modelo, proporção, task id, créditos, data e variantes. Não guarda chave, headers nem as URLs assinadas.
- Originais em `scripts/.runway-originals/` (ignorado pelo git).
- Sem imagem no manifest, a landing renderiza só o texto (`SiteImage` não desenha nada).
