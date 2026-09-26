# Minuta — geração inteligente de documentos

Transforme documentos repetitivos (contratos, declarações, propostas, procurações, termos, recibos, formulários de RH) em **geradores reutilizáveis**.

1. Envie um `.docx`.
2. Ele aparece em um editor visual. **Selecione** um trecho como “João da Silva” e clique em **Transformar em campo** — sem escrever `{{placeholders}}`.
3. O documento vira um gerador com **formulário automático** (máscaras e validações brasileiras) e **geração em lote** numa grade estilo Excel.
4. Saída em **DOCX e PDF reais** (LibreOffice), com histórico, links temporários e ZIP + relatório CSV para lotes.
5. **Kit de documentos**: agrupe geradores prontos que compartilham variáveis (nome, CPF, endereço…) — preencha uma vez e gere todos juntos, com download individual ou em ZIP.

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

Variáveis principais (todas em [.env.example](.env.example)): `SECRET_KEY`, `COOKIE_SECURE`, `AI_PROVIDER`/`AI_API_KEY`/`AI_MODEL`, `FILE_RETENTION_DAYS`, `SEED_DEMO`. Sem `AI_API_KEY` o produto usa **apenas regras determinísticas + heurísticas locais** e a interface avisa isso (“Sugestões locais — IA externa não configurada”).

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

1. **Cadastro** → novo workspace. **Novo gerador** → nome → envie `demo/contrato_prestacao_servicos.docx`.
2. No editor, **selecione “João da Silva”** → menu flutuante → **Transformar em campo** → “Nome do contratante”. Reutilize o campo em outra ocorrência.
3. Selecione “consultoria em desenvolvimento de software” → tipo **Lista suspensa** → cole 3 opções (uma por linha).
4. Aba **Sugestões** → **Aceitar alta confiança** (CPF, CNPJ, valor, datas).
5. Sem etapa de publicação: **Usar agora** (formulário com prévia ao vivo) → gere **DOCX** e **PDF**.
6. **Gerar em lote**: digite 3 linhas, cole intervalo do Excel, **Importar** `demo/lote_exemplo.xlsx` (mapeie colunas), corrija a célula inválida pelo painel de erros, **Gerar lote** → baixe **ZIP + relatório CSV**.
7. **Histórico** → status, versão, erros, expiração, **Repetir**.

## Testes

```bash
# Backend (SQLite, sem infraestrutura)
cd backend && .venv/Scripts/python -m pytest
# Backend contra PostgreSQL real
TEST_DATABASE_URL=postgresql://usuario:senha@localhost:5432/teste .venv/Scripts/python -m pytest
# Frontend: unidade (vetores compartilhados com o backend + grade) e tipos
cd frontend && npm test && npm run typecheck
# E2E + acessibilidade (stack já em execução em :3000; E2E_CHANNEL=msedge usa o Edge instalado)
cd frontend && npx playwright test
# Lint
cd backend && .venv/Scripts/python -m ruff check app seed tests
# Queda real do worker no meio de um lote (SIGKILL) com a stack Docker no ar: espera retomada sem duplicar arquivos
python scripts/crash_recovery_test.py
```

O que a suíte cobre: validações CPF/CNPJ (incl. alfanumérico) e tipos de campo; **vetores compartilhados backend↔frontend**; texto dividido em runs do DOCX, campo repetido, formatação, imagem, tabela, cabeçalho, rodapé; segurança de upload (ZIP bomb, macros, XXE, path traversal); **isolamento multi-tenant** (dois workspaces, chamadas de geradores **e** de kits + download assinado); **idempotência**; **falha parcial em lote**, retomada de job e **recuperação após queda do worker** (claim atômico, heartbeat, watchdog, perda de posse); geração sem etapa de publicação (uso imediato, restaurar versão, fixar); **kit de documentos** (detecção automática de campos compartilhados — por similaridade de rótulo e, opcionalmente, por **classificação semântica de papéis** via TypeSafe.ai/Jev, distinguindo "contratante" de "contratado" e reconhecendo sinônimos —, mapeamento manual, tipos incompatíveis, geração de todos os documentos do kit, ZIP + relatório); **detecção de campos no upload** (ano, mês como lista suspensa, numeração de sugestões duplicadas, papel de parte antes de um nome — ver D26); importação XLSX/CSV (mapeamento sugerido, **oferecer adicionar um valor novo à lista suspensa** durante a importação); provedor de IA (schema, retry, timeout, cache por hash, indisponibilidade); grade (colar TSV, desfazer, preencher); E2E dos três fluxos principais (individual, lote, kit); axe (WCAG A/AA).

## Resultados verificados (execução real, 25/09/2026)

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
- **Prévia do formulário** é uma aproximação em HTML do documento; o arquivo final é o DOCX/PDF.
- **PDF depende do LibreOffice**: fontes fora do Office (Calibri→Carlito, Arial→Liberation) podem alterar quebras de linha/página em relação ao Word. Sem `soffice`, PDF responde `PDF_CONVERTER_UNAVAILABLE` (o DOCX segue funcionando).
- **Sem assinatura eletrônica**, sem edição de PDF de entrada, sem colaboração em tempo real, sem convites de equipe (a UI de convites está no roadmap; os papéis `owner`/`member` existem e são aplicados).
- **IA**: sem chave, as sugestões vêm de heurísticas locais em português (conservadoras, com confiança moderada) — não é um modelo de linguagem. Com chave, o conteúdo do **modelo** (não os valores preenchidos) é enviado ao provedor apenas na análise; veja [SECURITY_AND_LGPD](docs/SECURITY_AND_LGPD.md).
- **Jobs em lote**: a entrega é *at-least-once*. Se um worker morrer no meio, o job fica parado por ≈ 1 a 1,5 min (heartbeat de 60 s + varredura de 15 s) e então é retomado sozinho; um bloco de até 20 linhas em andamento pode ser refeito (sem duplicar arquivos). Isso foi verificado com `docker kill` em lote real; **não** foi testada a queda do Redis/Postgres/MinIO no meio de um job nem carga com vários lotes simultâneos. O redelivery próprio do Dramatiq é probabilístico e não é usado como garantia (ver [D22](docs/DECISIONS.md)).
- **Métricas**: `/metrics` agrega do banco (consistente entre processos); métricas de fila vêm do exportador do Dramatiq (porta 9191 do worker).
- O acesso à área de transferência pelo navegador (copiar da grade) exige contexto seguro (`localhost` ou HTTPS).
- Compose é para desenvolvimento/demonstração (HTTP, senhas padrão). Produção exige TLS, segredos próprios, `APP_ENV=production` e serviços gerenciados (o app se recusa a subir em produção com `SECRET_KEY` padrão).
