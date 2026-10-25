# Sprint: teste grátis na landing, link para o cliente preencher, assinatura eletrônica

Especificação comum para os três agentes (engenharia, testes, segurança). Decisões novas entram em
`docs/DECISIONS.md` como **D38** (teste grátis), **D39** (link do cliente), **D40** (assinaturas), **D41** (segurança
da sprint, se necessário).

## Regras do projeto (valem para todos)

- Produto: **DocFeito** (rebranding D36). Interface e textos em **pt-BR**, no tom do produto: direto, sem jargão.
  Comentários de código em pt-BR, na densidade do código ao redor.
- Stack: FastAPI + SQLAlchemy 2 + Alembic (Postgres em produção; SQLite com `create_all` nos testes e no modo sem
  Docker), Dramatiq/Redis (worker com LibreOffice), MinIO/S3. Frontend Next.js 16 (App Router), React 19, TanStack
  Query, RHF+Zod, Tailwind v4 com os tokens do tema (`globals.css`). E2E com Playwright usando o Edge
  (`E2E_CHANNEL=msedge`).
- Migrations novas: `0009_*`, `0010_*`, `0011_*` em `backend/migrations/versions/`, uma por feature, em ordem.
- **Nunca** commitar segredo. Chaves de terceiros: arquivo fora do repositório ou secret do Docker, nunca `.env`.
  A chave da OpenRouter fica em `~/.minuta/openrouter.key` e só é lida pelo código (não imprimir, não logar).
- **Custo de IA real é limitado**: a conta tem ~US$ 6 de crédito. Cada agente pode gastar no máximo **US$ 0,50**
  em chamadas reais (anote o custo informado pela OpenRouter). Estresse e testes automáticos usam IA **falsa**
  (servidor local ou `MockTransport`), nunca a real.
- Não mexer nos stacks Docker `minuta` (3000/8100) nem `minuta-fase0` (3210/8110): quem reconstrói é o
  coordenador. Para testar, suba o backend sem Docker (SQLite, `JOB_BACKEND=thread`) e o front com
  `npx next dev --webpack` (o Turbopack não aceita `node_modules` por junção) nas portas reservadas abaixo.
- Não fazer push. Commits pequenos, mensagem em pt-BR, terminando com
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Adicionar arquivos um a um (nunca `git add -A`).
- Antes de commitar: `ruff check app tests` e `pytest -q` (backend), `npx tsc --noEmit -p .` e `npx eslint` nos
  arquivos tocados (frontend).

| Agente | Pasta (git worktree) | Branch | Portas API / web |
|---|---|---|---|
| Engenharia | `.worktrees/eng` | `claude/sprint-features` | 8140 / 3340 |
| Testes | `.worktrees/qa` | `claude/sprint-qa` | 8150 / 3350 |
| Segurança | `.worktrees/sec` | `claude/sprint-seguranca` | 8160 / 3360 |

O venv do backend é o da pasta principal: `C:/Users/daniel.rosa/Documents/gerador-documento/backend/.venv`.
Cada worktree tem `frontend/node_modules` como junção para o da pasta principal — para removê-la use
`cmd /c rmdir`, nunca remoção recursiva (apagaria o `node_modules` verdadeiro).

Subir o backend sem Docker (exemplo para a porta 8140), de dentro de `<worktree>/backend`:

```bash
export DATABASE_URL="sqlite:///./data/dev.db" STORAGE_BACKEND=local JOB_BACKEND=thread PDF_CONVERTER=none \
  APP_ENV=development PUBLIC_WEB_URL=http://localhost:3340 ALLOWED_ORIGINS=http://localhost:3340 SEED_DEMO_PASSWORD=demo12345
<venv>/python -m uvicorn app.main:app --port 8140      # cria as tabelas (SQLite)
<venv>/python -m app.cli seed                           # depois que a API subiu: dados de demonstração
cd ../frontend && API_INTERNAL_URL=http://127.0.0.1:8140 npx next dev --webpack -p 3340
```

IA falsa para testes/estresse: `OPENROUTER_BASE_URL=http://127.0.0.1:<porta>/api/v1` apontando para um servidor
local que responda `/chat/completions` e `/models` no formato da OpenRouter (o agente de testes cria e documenta em
`scripts/fake_openrouter.py`), com `EXTERNAL_AI_ENABLED=true` e `OPENROUTER_API_KEY=sk-or-v1-falsa…`.

---

## A — Teste grátis na landing, sem cadastro (D38)

**Por quê:** é o que mais converte. O visitante envia o documento DELE, vê a IA marcar os campos na hora e cria a
conta para guardar o modelo.

**Fluxo**
1. Na landing (`frontend/src/app/page.tsx`, seção da demonstração), um bloco "Teste com o seu documento": arrastar
   ou escolher `.docx` ou PDF digitado (até **5 MB** e **10 páginas**), com aviso curto de privacidade ("apagado em
   1 hora; não use dados de terceiros sem autorização").
2. `POST /api/v1/public/trials` (multipart `file` + `turnstile_token` opcional + campo-armadilha `website`) →
   `{token, status: "processing"}`. O processamento (conversão do PDF pelo `pdfconv`, leitura do .docx, regras e IA)
   roda no worker; o front consulta `GET /api/v1/public/trials/{token}` até `status: "done" | "failed"`.
3. Resultado: prévia do documento com os campos destacados (mesmo visual do editor/prévia do app, pode ser só
   leitura) e a lista de campos encontrados (nome, tipo, trecho). CTA: "Criar conta grátis e salvar este modelo".
4. `/register?trial=<token>`: depois do cadastro (ou login), `POST /api/v1/trials/{token}/claim` (autenticado) cria o
   modelo no espaço de trabalho com o documento e as sugestões, e leva para a etapa Campos. Token de teste vale
   **1 hora**; depois disso, arquivo e resultado são apagados por um job de limpeza.

**Controles de custo e abuso (obrigatórios)**
- Trava geral `TRIAL_ENABLED` (padrão `true` em dev, documentar).
- Limites por **IP real** (ver "IP do cliente" abaixo): 3 testes/hora e 10/dia; por **/24 (IPv4) ou /64 (IPv6)**:
  30/dia. Processamentos simultâneos de teste no sistema todo: máximo `TRIAL_MAX_CONCURRENT` (padrão 3); acima disso,
  fila curta ou "tente em instantes".
- **Orçamento diário de IA só para testes anônimos** (`TRIAL_AI_DAILY_BUDGET_USD`, padrão 0,50) reservado no mesmo
  mecanismo do `ai_budget` (uma finalidade nova, p.ex. `trial`, e workspace nulo). Esgotou → o teste continua só
  com as regras locais (sem custo), com aviso discreto. A IA do teste lê no máximo os primeiros **6.000 caracteres**.
- **Cloudflare Turnstile** quando `TURNSTILE_SECRET_KEY` estiver configurada (validar no servidor; sem a chave, o
  teste funciona e o limite por IP segura). Campo-armadilha escondido: preenchido → responde como sucesso mas não
  processa nada.
- Arquivo validado pelos mesmos caminhos de upload (`validate_docx`, PDF só pelo `pdfconv` isolado).
- Nada de gerar PDF/DOCX no teste anônimo (LibreOffice é caro): só a análise.

**IP do cliente:** hoje `uvicorn --forwarded-allow-ips=*` faz a API confiar em qualquer `X-Forwarded-For` (falsificável
por quem chama a API direto) e, atrás do proxy do Next, todos podem chegar com o mesmo IP. Precisa de uma função única
`client_ip(request)` com lista de proxies confiáveis (`TRUSTED_PROXIES`, padrão: rede interna do Docker e loopback),
usada por todos os limites. Isso é pré-requisito de A e B (o agente de segurança detalha).

## B — Link para o cliente preencher (D39)

**Por quê:** acaba com o vaivém de mensagens pedindo dados. O profissional manda um link; o cliente preenche ou
fotografa os documentos pelo celular; o profissional confere e gera.

**Lado do profissional**
- Na tela Gerar (modelo e kit): botão "Pedir dados ao cliente" → diálogo: quais campos pedir (padrão: os
  obrigatórios sem valor padrão), mensagem opcional, validade (padrão 7 dias, máximo 30), permitir enviar fotos dos
  documentos (usa a leitura por IA da D37, contando na cota do espaço; no máximo 3 leituras por link), valores já
  preenchidos que o cliente pode ver/editar ou não.
- Cria `client_requests` (token aleatório de 32 bytes, guardado só como hash; o link mostra o token uma vez), mostra o
  link, um botão "Copiar mensagem para WhatsApp" (texto pronto + `https://wa.me/?text=`) e "Copiar link".
- Caixa "Respostas recebidas" (no Início e por modelo): status aberto / respondido / expirado / cancelado; abrir uma
  resposta leva à tela Gerar com os valores já no formulário (o profissional confere e gera). Cancelar link. Aviso no
  app (contador) e e-mail se houver SMTP.

**Lado do cliente** (página pública `/r/{token}`, mobile-first)
- Mostra o nome do espaço de trabalho e do documento, a mensagem, só os campos pedidos, com as mesmas máscaras e
  validações do formulário (CPF, datas, valores…). Botão "Preencher com a foto do documento" quando permitido.
- Enviar → página de agradecimento. Pode corrigir e reenviar enquanto o profissional não abrir a resposta.
- Nada de dados de outros clientes ou do modelo além dos rótulos dos campos pedidos.

**Segurança:** rotas públicas sob `/api/v1/public/requests/{token}`; limite por IP e por token; tamanho de anexos
igual à D37; resposta armazenada até ser usada + retenção configurável (padrão 30 dias depois de respondida);
auditoria (criação, abertura, envio, cancelamento) sem os valores.

## C — Assinatura eletrônica: integrações (D40)

**Por quê:** fechar o ciclo dentro do app — gerou, mandou assinar, voltou assinado para o histórico.

**Arquitetura**
- `backend/app/modules/signatures/`: interface comum de provedor —
  `create_envelope(pdf, nome_arquivo, signatários, opções) -> Envelope(id_externo, links_por_signatário)`,
  `status(id_externo)`, `download_signed(id_externo) -> bytes` (+ trilha/certificado quando houver),
  `cancel(id_externo)`, `parse_webhook(headers, corpo) -> evento` com verificação de assinatura do provedor.
- Provedores (pesquisar a API ATUAL na documentação oficial antes de codificar; preferir sandbox):
  **ZapSign**, **Clicksign**, **D4Sign**, **Autentique**, **DocuSign** (eSignature REST), **Adobe Acrobat Sign** e
  outros muito usados no Brasil se a API for pública e estável (avaliar: Assinafy, Contraktor, Lacuna/Signer,
  Certisign Portal de Assinaturas).
- **gov.br**: verificar se existe API de assinatura gov.br disponível para empresas privadas (a do ITI costuma ser
  para órgãos públicos/convênio). Se não houver, implementar o **fluxo assistido**: o profissional baixa o PDF; o
  signatário assina no Assinador oficial (`assinador.iti.br`, com a conta gov.br prata/ouro); o PDF assinado volta
  por upload (do profissional ou por link para o signatário); o servidor **verifica a assinatura PAdES** (com
  pyHanko ou equivalente, rodando no serviço isolado `pdfconv` — PDF de fora não é aberto na API) e mostra quem
  assinou e quando; link para conferência pública em `validar.iti.gov.br`. Mesma verificação vale para assinatura
  com certificado ICP-Brasil (A1/A3) feita fora do app.
- Credenciais por espaço de trabalho (`signature_providers`): token/chave **criptografados** (Fernet, chave em
  `ENCRYPTION_KEY`/arquivo secreto; adicionar `cryptography`), modo sandbox/produção, segredo de webhook. Tela
  "Configurações → Assinatura eletrônica" (só o proprietário) com "Testar conexão".
- Envio: a partir do resultado de uma geração (diálogo do job e Histórico): "Enviar para assinatura" → provedor
  configurado + signatários (nome, e-mail, celular/WhatsApp, CPF opcional, ordem, método de autenticação quando o
  provedor permitir) → `signature_requests`. Status por webhook `POST /api/v1/signatures/webhook/{provedor}/{chave}`
  (chave aleatória por espaço) + consulta periódica no worker como reserva. Concluído → baixa o PDF assinado (e
  trilha de auditoria do provedor) e guarda como arquivo da geração (tipo `signed`), visível no Histórico.
- Testes sem rede: cada adaptador com `httpx.MockTransport` reproduzindo os formatos documentados (criar, status,
  baixar, webhook com assinatura válida e inválida). Teste real só com credenciais de sandbox fornecidas pelo Daniel
  (pular quando ausentes) — listar no relatório o que ele precisa criar em cada provedor.
- Plano/cota: assinaturas contam por mês por plano (definir números no `plans.json` nas duas cópias).

## Entregas de cada agente

- **Engenharia:** A → B → C, nessa ordem, cada uma com migration, testes (pytest sem rede + E2E), docs (D38–D40,
  `docs/API.md`, README) e um commit por feature (ou por etapa grande) em `claude/sprint-features`. Ao terminar cada
  feature, relatar ao coordenador o commit e como subir/testar.
- **Testes:** infraestrutura (IA falsa, script para subir o stack de teste, estresse com `httpx`/asyncio em
  `scripts/stress/`), depois testes de ponta a ponta e de carga de cada feature entregue, incluindo os casos-limite
  (arquivos grandes, PDFs estranhos, links expirados, concorrência, webhooks repetidos/fora de ordem). Relatar bugs com
  passo a passo; commitar testes em `claude/sprint-qa`.
- **Segurança:** modelo de ameaças das três features e do que já existe que elas tocam (IP/limites, uploads, IA,
  webhooks, rotas públicas, credenciais), em `docs/SEGURANCA_SPRINT.md`, com requisitos priorizados; depois revisão
  do código entregue e tentativas reais de ataque contra o stack local (sem IA real), com testes de regressão em
  `claude/sprint-seguranca`. Pergunta-chave do Daniel: **o teste grátis da landing pode virar um ataque que gera
  custo?** — responder com números (pior caso por hora/dia com e sem as travas).
