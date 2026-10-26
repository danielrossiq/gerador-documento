# DocFeito (ex-Minuta): instruções para o Claude

**Antes de tudo, leia `docs/HANDOFF.md`.** Ele traz o estado atual, a sprint em andamento (A teste grátis, B link do
cliente, C assinatura eletrônica), as pendências e como rodar o projeto. A especificação da sprint está em
`docs/specs/SPRINT_TESTE_LINK_ASSINATURA.md`, e as decisões de arquitetura em `docs/DECISIONS.md` (D1–D39).

- Interface, textos, commits e comentários em **pt-BR**, no tom do produto: direto, sem jargão.
- Backend: FastAPI + SQLAlchemy 2 + Alembic, em `backend/`. Frontend: Next.js 16 + React 19 + TanStack Query +
  Tailwind v4, em `frontend/`. Rode o front com `next dev --webpack`.
- Antes de commitar:
  - no backend: `ruff check app tests` e `pytest -q`;
  - no frontend: `npx tsc --noEmit -p .` e `npx eslint` nos arquivos tocados.
- **Nunca** commite, imprima ou registre em log segredos (OpenRouter, Stripe, TypeSafe, provedores de assinatura).
- **IA real custa dinheiro.** Testes e estresse usam a IA falsa (`scripts/fake_openrouter.py` ou `httpx.MockTransport`).
- Commits pequenos, adicionando arquivos um a um. Mensagem termina com
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Push só quando o Daniel pedir.
