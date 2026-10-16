# Minuta — geração inteligente de documentos

Transforme documentos repetitivos (contratos, declarações, propostas, procurações, termos, recibos, formulários de RH) em **modelos reutilizáveis**.

Cada modelo passa por 4 etapas, sempre visíveis no topo da tela — **Documento → Campos → Revisão → Gerar**:

1. **Documento**: envie um `.docx` que você já usa. **PDF digitado** (exportado do Word, Google Docs ou de um sistema) também vira Word editável, mas fica **desligado por padrão** no piloto (`PDF_IMPORT_ENABLED`, ver D30); PDF digitalizado é sempre recusado, com explicação. Dá para trocar o documento depois; os campos são reposicionados.
2. **Campos**: no editor visual, **selecione** um trecho como “João da Silva” e clique em **Transformar em campo** — sem escrever `{{placeholders}}`. Sugestões automáticas (CPF, CNPJ, datas, valores…) e avisos de nome repetido, lista sem opções e campo fora do documento.
3. **Revisão**: o documento com **dados de exemplo**, a lista do que falta ajustar e o nome dos arquivos gerados.
4. **Gerar**: **um documento** num formulário automático (máscaras e validações brasileiras, prévia ao vivo, rascunho salvo sozinho) ou **vários** numa grade estilo Excel (colar do Excel, importar XLSX/CSV, erros por célula, resumo antes de gerar).
4. Saída em **DOCX e PDF reais** (LibreOffice), com histórico, links temporários e ZIP + relatório CSV para lotes.
5. **Cole aqui e a gente descobre o modelo** (página inicial): cole as linhas de uma planilha com a linha de títulos; o sistema identifica qual modelo ela preenche, mostra como cada coluna vira um campo e leva as linhas para o lote. Sem linha de títulos, só o conteúdo (CPF, datas…) é usado e nada é enviado ao classificador externo.
6. **Kit de documentos**: agrupe modelos prontos que compartilham variáveis (nome, CPF, endereço…) — preencha uma vez e gere todos juntos, com download individual ou em ZIP.

Stack: Next.js 16 · React 19 · TipTap · TanStack Query/Virtual · FastAPI · SQLAlchemy 2 · PostgreSQL · Redis + Dramatiq · MinIO/S3 · LibreOffice headless.

> Documentação: [ARCHITECTURE](docs/ARCHITECTURE.md) · [DECISIONS](docs/DECISIONS.md) · [DATA_MODEL](docs/DATA_MODEL.md) · [SECURITY_AND_LGPD](docs/SECURITY_AND_LGPD.md) · [API](docs/API.md) · [ROADMAP](docs/ROADMAP.md) · [DEMO](docs/DEMO.md)

## Subir tudo com Docker (recomendado)

Requisitos: Docker Desktop/Engine com Compose v2.

```bash
docker compose up --build
```

Na primeira subida o serviço `migrate` aplica as migrations do Alembic e cria os dados de demonstração. Depois:

| O quê | Onde |
|---|---|
| Aplicação | http://localhost:3000 |
| API + OpenAPI | http://localhost:8100/api/docs |
| Console do MinIO | http://localhost:9101 (`minuta` / `minuta-secret-123`) |
| **Login de demonstração** | `demo@minuta.app` / `demo12345` |
| Outro workspace (isolamento) | `outra@minuta.app` / `demo12345` |

Portas do host configuráveis em `.env` (copie `.env.example`): `WEB_PORT`, `API_PORT`, `MINIO_CONSOLE_PORT`. Postgres e Redis **não** são publicados no host. As portas padrão evitam 80/5432/8000 de propósito.

```bash
docker compose up --scale worker=3     # mais workers de geração
docker compose logs -f worker          # acompanhar a geração
docker compose down                    # parar (mantém dados)
docker compose down -v                 # parar e APAGAR bancos/arquivos
```

Variáveis principais (todas em [.env.example](.env.example)): `SECRET_KEY`, `COOKIE_SECURE`, `AI_PROVIDER`/`AI_API_KEY`/`AI_MODEL`, `FILE_RETENTION_DAYS`, `SEED_DEMO`. **Travas do piloto** (padrão desligado): `EXTERNAL_AI_ENABLED` (sem ela nenhuma IA externa é chamada, mesmo com chave) e `PDF_IMPORT_ENABLED`. Retenção, exportação e eliminação: [RETENCAO_E_ELIMINACAO.md](docs/RETENCAO_E_ELIMINACAO.md). Sem `AI_API_KEY` o produto usa **apenas regras determinísticas + heurísticas locais** e a interface avisa isso (“Sugestões locais — IA externa não configurada”).

## Rodar sem Docker (desenvolvimento)

Python 3.12+ e Node 22+. Sem Docker o app usa SQLite + storage local + jobs em threads; **PDF exige o `soffice` (LibreOffice) no PATH** — sem ele o DOCX funciona e o PDF responde com erro claro.

```bash
# backend (porta 8100 — 8000 costuma estar ocupada)
cd backend
python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev,postgres]"   # Linux/macOS: .venv/bin/python
export PDF_CONVERTER=none JOB_BACKEND=thread          # PowerShell: $env:PDF_CONVERTER="none"
.venv/Scripts/python -m app.cli seed                    # cria dados de demonstração (SQLite)
.venv/Scripts/python -m uvicorn app.main:app --port 8100

# frontend (outro terminal)
cd frontend
npm install
API_INTERNAL_URL=http://127.0.0.1:8100 npm run dev      # PowerShell: $env:API_INTERNAL_URL="http://127.0.0.1:8100"
```

## Roteiro de demonstração (10 minutos)

Veja o passo a passo completo em [docs/DEMO.md](docs/DEMO.md). Resumo, com os arquivos em `demo/`:

1. **Cadastro** → no **Início**, envie `demo/contrato_prestacao_servicos.docx` (ou `.pdf`, que é digitado) ou abra **Novo modelo** → (etapa **Documento**) nome opcional.
2. (etapa **Campos**) **Selecione “João da Silva”** → menu flutuante → **Transformar em campo** → “Nome do contratante”. Na outra ocorrência, o editor avisa que o nome já existe e oferece **usar o campo existente**.
3. Selecione “consultoria em desenvolvimento de software” → tipo **Lista de opções** → cole 3 opções (uma por linha).
4. Aba **Sugestões** → **Aceitar as recomendadas** (CPF, CNPJ, valor, datas).
5. **Próximo: Revisão** → confira as pendências e a **prévia com dados de exemplo**.
6. (etapa **Gerar** → **Um documento**) **Preencher com dados de exemplo** ou digite → gere **Word** e **PDF**.
7. **Vários documentos**: digite 3 linhas, cole um intervalo do Excel, **Importar planilha** `demo/lote_exemplo.xlsx` (mapeie colunas), corrija a célula inválida pela lista de erros, **Gerar N documentos** (confira o resumo) → baixe **ZIP + relatório CSV**.
8. **Histórico** → status, versão, erros, expiração, **Repetir**.

## Testes

```bash
# Backend (SQLite, sem infraestrutura)
cd backend && .venv/Scripts/python -m pytest
# Backend contra PostgreSQL real
TEST_DATABASE_URL=postgresql://usuario:senha@localhost:5432/teste .venv/Scripts/python -m pytest
# Migrations (0001 → head, downgrade com dados, upgrade, alembic check) num PostgreSQL DESCARTÁVEL (o teste recria o schema)
MIGRATION_DATABASE_URL=postgresql://usuario:senha@localhost:5432/descartavel .venv/Scripts/python -m pytest tests/test_oab.py -k migration
# Frontend: unidade (vetores compartilhados com o backend + grade) e tipos
cd frontend && npm test && npm run typecheck
# E2E + acessibilidade (stack já em execução em :3000, ou E2E_BASE_URL=http://localhost:PORTA; E2E_CHANNEL=msedge usa o Edge instalado;
# E2E_EXECUTABLE_PATH=/caminho/do/chromium usa um Chromium já instalado)
cd frontend && npx playwright test
# Recapturar docs/screenshots
cd frontend && CAPTURE_SCREENSHOTS=1 npx playwright test e2e/capture-screenshots.spec.ts
# Lint
cd backend && .venv/Scripts/python -m ruff check app seed tests
# Queda real do worker no meio de um lote (SIGKILL) com a stack Docker no ar: espera retomada sem duplicar arquivos
python scripts/crash_recovery_test.py
```

O que a suíte cobre: validações CPF/CNPJ (incl. alfanumérico) e tipos de campo; **vetores compartilhados backend↔frontend**; texto dividido em runs do DOCX, campo repetido, formatação, imagem, tabela, cabeçalho, rodapé; segurança de upload (ZIP bomb, macros, XXE, path traversal); **isolamento multi-tenant** (dois workspaces, chamadas de geradores **e** de kits + download assinado); **idempotência**; **falha parcial em lote**, retomada de job e **recuperação após queda do worker** (claim atômico, heartbeat, watchdog, perda de posse); geração sem etapa de publicação (uso imediato, restaurar versão, fixar); **kit de documentos** (detecção automática de campos compartilhados — por similaridade de rótulo e, opcionalmente, por **classificação semântica de papéis** via TypeSafe.ai/Jev, distinguindo "contratante" de "contratado" e reconhecendo sinônimos —, mapeamento manual, tipos incompatíveis, geração de todos os documentos do kit, ZIP + relatório); **detecção de campos no upload** (ano, mês como lista suspensa, numeração de sugestões duplicadas, papel de parte antes de um nome — ver D26); importação XLSX/CSV (mapeamento sugerido, **oferecer adicionar um valor novo à lista suspensa** durante a importação); provedor de IA (schema, retry, timeout, cache por hash, indisponibilidade); grade (colar TSV, desfazer, preencher); **pendências dos campos, ordem do documento, dados de exemplo e nome de arquivo** (unidade); E2E dos fluxos principais pelas 4 etapas (individual, modelo sem documento, editor com pendências e salvamento, lote com planilha vazia/linha de exemplo, kit, PDF digitado × digitalizado, colar planilha com e sem títulos, celular 390 px); **PDF digitado vs digitalizado** e **colar sem títulos não chega ao classificador externo** (backend); axe (WCAG A/AA) em todas as etapas do modelo.

## Resultados verificados — Fase 0 (execução real, 15/10/2026)

Ambiente: stack Docker **recriada do zero** num projeto Compose separado (`docker compose -p minuta-fase0`, portas 3210/8110/9111, volumes novos — nenhum volume ou dado existente foi apagado ou alterado), imagens reconstruídas com o código desta branch; E2E no **Microsoft Edge** (`E2E_CHANNEL=msedge`); testes de backend em SQLite (modo local).

| Verificação | Resultado |
|---|---|
| Backend `pytest` | **273 passed** (inclui PDF digitado × digitalizado, `/batch/identify`, colar sem títulos, `{modelo}`) |
| Backend `ruff check` · `ruff format --check` | 0 erros · 99 arquivos formatados |
| Frontend `vitest` | **87 passed** |
| Frontend `tsc` (app + testes) · `next build` | 0 erros |
| Frontend `eslint` | 0 erros, 15 avisos (regras do React Compiler, os mesmos de antes) |
| Stack Docker do zero (`up -d --build`: postgres 17, redis, minio, migrate + seed, api, worker, web) | todos os serviços saudáveis; migrations 0001 → 0004 aplicadas |
| E2E Playwright (Edge) contra a stack Docker | **15 passed**, 2 de captura de tela (sob demanda): fluxo individual (Documento → Campos → Revisão → Gerar), modelo sem documento, editor, 4 de lote, kit, **PDF digitado aceito / digitalizado recusado**, **colar com e sem títulos**, **celular 390 px**, 3× axe (WCAG 2 A/AA) + teclado |
| Home em 390 px | sem rolagem horizontal (corrigido: a lista "Seus modelos" chegava a 435 px) |

Observações da execução:
- O cadastro é limitado a **10 por hora por IP** (`app/modules/auth/service.py`). A suíte E2E cria ~7 contas por execução; para repeti-la na mesma hora numa stack de desenvolvimento, apague a chave `rl:register:*` do Redis **dessa stack** (`docker compose exec redis redis-cli --scan --pattern 'rl:register:*'`).
- Não reexecutado nesta fase: PostgreSQL via `TEST_DATABASE_URL`, lote de 1.000 e queda do worker (`scripts/crash_recovery_test.py`).

## Resultados verificados — revisão de UX (execução real, 26/09/2026)

Ambiente: modo local sem Docker (SQLite, storage local, jobs em thread), LibreOffice 24.2 (Writer), Chromium 141 via Playwright 1.63, `next build` + `next start`. **Não** reexecutado nesta revisão: PostgreSQL, stack Docker, lote de 1.000 e queda do worker (tabela abaixo, da versão anterior).

| Verificação | Resultado |
|---|---|
| Backend `pytest` (SQLite) | **246 passed** (inclui a correção das sugestões obsoletas; antes: 245 passed + 1 failed) |
| Backend `ruff check` | 0 erros |
| Frontend `vitest` | **81 passed** (72 + 9 novos: pendências, ordem do documento, exemplos, nome de arquivo) |
| Frontend `tsc` (app + testes) · `eslint` · `next build` | 0 erros (eslint: 15 avisos das regras do React Compiler, os mesmos de antes) |
| E2E Playwright (Chromium) contra `next start` + API local | **11 passed** (+2 de captura de tela, sob demanda): fluxo individual pelas 4 etapas com Word **e PDF reais**, gerador sem documento, editor (pendências e salvamento ao trocar de campo), 4 de lote, kit, 3× axe (WCAG 2 A/AA) + teclado |
| Largura em 390 px (celular) | nenhuma tela com rolagem horizontal (antes: painel com 572 px e histórico com 913 px) |

## Resultados verificados (versão anterior, 25/09/2026)

| Verificação | Resultado |
|---|---|
| Backend `pytest` (SQLite) | **242 passed** |
| Backend `pytest` contra **PostgreSQL 17** | **242 passed** |
| Migrations Alembic (PostgreSQL 17) | `upgrade head` (0001 → 0004) → `alembic check` sem divergências → `downgrade` → `upgrade head` → `alembic check` sem divergências |
| Frontend `vitest` (48 vetores compartilhados + grade) | **72 passed** |
| Frontend `tsc` (app + testes) · `eslint` · `next build` | 0 erros (eslint: 16 avisos das regras do React Compiler, intencionais — ver `eslint.config.mjs`) |
| Backend `ruff check` | 0 erros |
| E2E Playwright (Edge) na stack Docker de produção (rebuild completo, banco recriado do zero, classificador TypeSafe **ativo de verdade**, não mockado) | **8 passed**: fluxo individual, fluxo de lote, lote com linhas inválidas, **importação com opção nova na lista suspensa**, **fluxo de kit** (detecção automática, geração, ZIP), 3× axe (WCAG 2 A/AA) + teclado |
| **Lote de 1.000 documentos** (DOCX **e** PDF, 2.000 arquivos, 80 MB) na stack Docker | **1000/1000 ok em 100 s** (≈100 ms/doc) com 1 container de worker (2 processos × 4 threads); ZIP 66,9 MB com 1000 docx + 1000 pdf + `relatorio.csv` |
| **Queda real do worker** (`docker kill` = SIGKILL em lote de 400 DOCX+PDF, parado em 100/400) | job retomado sozinho pelo watchdog em **94 s** e **101 s** (2 execuções): 400/400 `succeeded`, 2 tentativas, **0 arquivos duplicados** (400 DOCX + 400 PDF + ZIP + relatório) |
| PDF real (LibreOffice 25.2) | 1ª conversão 1,1 s a frio, 0,4 s a quente, 10 PDFs em 1 invocação = 0,9 s |

> Não medido: navegadores diferentes do Edge/Chromium, leitores de tela reais, carga concorrente de vários lotes, Word como visualizador do DOCX gerado (o DOCX foi validado por `python-docx`, LibreOffice e testes de estrutura).

## Estrutura

```
backend/   app/{core,db,docx_engine,adapters,modules,worker} · migrations/ · seed/ · tests/ · Dockerfile
scripts/   crash_recovery_test.py  (teste real de queda do worker)
frontend/  src/{app,components,lib} · e2e/ · Dockerfile
shared/    field-vectors.json  (casos de teste compartilhados backend ↔ frontend)
demo/      contrato .docx e lotes .xlsx/.csv de exemplo (dados fictícios)
docs/      ARCHITECTURE, DECISIONS, DATA_MODEL, SECURITY_AND_LGPD, API, ROADMAP, DEMO, screenshots
```

## Limitações conhecidas (leia antes de usar em produção)

- **Fidelidade do DOCX**: textos, negrito/itálico/sublinhado/tachado, cabeçalho, rodapé, tabelas, imagens e quebras de página são preservados; **parágrafos alterados perdem alterações rastreadas** (`w:ins/w:del`) e fica sem hyperlink apenas quando o texto dele é reescrito. Imagens, campos do Word (ex.: número de página), controles de conteúdo e quebras aparecem como blocos **não editáveis**, mantidos no lugar.
- **Tabelas**: só o texto das células é editável; adicionar/remover linhas/colunas não é suportado (a estrutura é travada de propósito).
- **Editor "paginado"**: o visual é contínuo (uma folha A4 com cabeçalho no topo e rodapé no fim). A paginação real só existe no DOCX/PDF gerados.
- **Prévia do formulário e da revisão** é uma aproximação em HTML do documento; o arquivo final é o DOCX/PDF.
- **Rascunhos** do formulário individual e da planilha de vários documentos ficam **só no navegador** (`localStorage`): não acompanham a pessoa em outro computador e somem se ela limpar os dados do site. Nada preenchido vai ao servidor antes de gerar.
- **Pendências dos campos** (nome repetido, lista sem opções, fora do documento) são avisos: a geração não é bloqueada (nem pelo servidor).
- **PDF depende do LibreOffice**: fontes fora do Office (Calibri→Carlito, Arial→Liberation) podem alterar quebras de linha/página em relação ao Word. Sem `soffice`, PDF responde `PDF_CONVERTER_UNAVAILABLE` (o DOCX segue funcionando).
- **Sem assinatura eletrônica**, sem edição de PDF de entrada, sem colaboração em tempo real, sem convites de equipe (a UI de convites está no roadmap; os papéis `owner`/`member` existem e são aplicados).
- **IA**: sem chave, as sugestões vêm de heurísticas locais em português (conservadoras, com confiança moderada) — não é um modelo de linguagem. Com chave, o conteúdo do **modelo** (não os valores preenchidos) é enviado ao provedor apenas na análise; veja [SECURITY_AND_LGPD](docs/SECURITY_AND_LGPD.md).
- **Jobs em lote**: a entrega é *at-least-once*. Se um worker morrer no meio, o job fica parado por ≈ 1 a 1,5 min (heartbeat de 60 s + varredura de 15 s) e então é retomado sozinho; um bloco de até 20 linhas em andamento pode ser refeito (sem duplicar arquivos). Isso foi verificado com `docker kill` em lote real; **não** foi testada a queda do Redis/Postgres/MinIO no meio de um job nem carga com vários lotes simultâneos. O redelivery próprio do Dramatiq é probabilístico e não é usado como garantia (ver [D22](docs/DECISIONS.md)).
- **Métricas**: `/metrics` agrega do banco (consistente entre processos); métricas de fila vêm do exportador do Dramatiq (porta 9191 do worker).
- O acesso à área de transferência pelo navegador (copiar da grade) exige contexto seguro (`localhost` ou HTTPS).
- Compose é para desenvolvimento/demonstração (HTTP, senhas padrão). Produção exige TLS, segredos próprios, `APP_ENV=production` e serviços gerenciados (o app se recusa a subir em produção com `SECRET_KEY` padrão).
