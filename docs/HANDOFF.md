# Passagem de contexto: sessão local → sessão na nuvem (26/10/2026)

Repositório: **github.com/danielrossiq/gerador-documento**. Branch para continuar: **`claude/repaginacao-v3`**.
Ela já contém tudo: rebranding, IA, cobrança, PDF, foto, além das três branches da sprint juntadas.
Produto: **DocFeito** (antes "Minuta"; rebranding em D36). Dono: Daniel. Interface, textos, commits e comentários em pt-BR.

## 1. Onde o projeto está

| Área | Estado | Onde ler |
|---|---|---|
| Núcleo (modelos .docx, campos, geração em lote, kits, histórico) | pronto | `docs/ARCHITECTURE.md`, `docs/DATA_MODEL.md`, `docs/API.md` |
| Rebranding DocFeito (logo, paleta, landing, vídeo, manual de marca) | pronto | D36, `docs/MARCA.md`, `docs/SITE.md` |
| IA pela OpenRouter: detectar campos, preencher por texto, revisar | pronto | D33, `docs/IA.md` |
| Preencher pela foto/PDF dos documentos do cliente | pronto | D37 |
| Cobrança Stripe (cartão + Pix) | pronta, desligada por padrão; modo teste montado | D34, `docs/PAGAMENTOS.md` |
| PDF como modelo, com conversão isolada no contêiner `pdfconv` | pronto | D35 |
| Fidelidade PDF→DOCX (bancada `app/eval/fidelity.py`, modo fluxo e "layout exato") | bom, com pendências (§4) | D35 e código |
| **Sprint A**: teste grátis na landing, sem cadastro | **pronto, revisado por QA e segurança** | D38, spec abaixo |
| **Sprint B**: link para o cliente preencher | **pronta para revisão** (`e11aa36` + `03db4ed`), falta QA e segurança | D39, spec |
| **Sprint C**: assinatura eletrônica (ZapSign, Clicksign, D4Sign, Autentique, DocuSign, Adobe Sign, gov.br) | **não começada** | D40, spec |

A especificação completa da sprint, com as regras para todos, requisitos de segurança e o que cada agente entrega, está em
`docs/specs/SPRINT_TESTE_LINK_ASSINATURA.md`. **Leia antes de mexer em A, B ou C.**

## 2. A sprint e como ela foi tocada

Na sessão local, três agentes trabalhavam em git worktrees separadas. As branches deles já foram juntadas em
`claude/repaginacao-v3` e também estão no GitHub:

- `claude/sprint-features` (engenheiro): `e1e6d5e` IP real, `b1968ac` A, `0091fbc` correções da revisão, `e11aa36` WIP da B.
- `claude/sprint-qa` (testes e estresse): `scripts/fake_openrouter.py`, `scripts/stack_local.sh`,
  `scripts/stress/` (`run.py`, `trial_probe.py`, `trial_expiry.py`, `bomb_generation.py`),
  `backend/tests/test_qa_robustness.py`, `test_qa_trials.py`, `frontend/e2e/trial-qa.spec.ts`.
- `claude/sprint-seguranca` (segurança): `docs/SEGURANCA_SPRINT.md` (modelo de ameaças, fases 1, 2 e 4.1),
  `backend/tests/test_trial_security.py`, `test_security_phase2.py`.

Na nuvem, o mais simples é seguir numa branch só. Se quiser repetir o esquema de engenheiro, testador e segurança,
use o spec como roteiro.

### A — Teste grátis (D38): pronto

O que existe:
- **Rotas:** `POST /api/v1/public/trials` (multipart `file`, `turnstile_token`, `website` = armadilha),
  `GET /public/trials/{token}`, `GET /public/trials/config` e `POST /trials/{token}/claim` (com sessão).
- **Processamento:** fila `trial` no worker, sem retry. A limpeza apaga o teste em até TTL (1 h) + 5 min.
- **Front:** bloco `#teste` na landing; `/register?trial=` e `/login?trial=` guardam o modelo na conta.

Travas confirmadas pelo QA e pela segurança:
- **IP real:** o Next acrescenta o IP do socket ao `X-Forwarded-For` (`src/instrumentation.ts`). `app/core/net.py:client_ip`
  só aceita o cabeçalho vindo de `TRUSTED_PROXIES`, até `TRUSTED_PROXY_HOPS`. O uvicorn roda com `--no-proxy-headers`.
- **Limites por tentativa (chaves HMAC):**
  - 3 por hora por IP, ou 6 com Turnstile aprovado;
  - 10 por dia por IP;
  - 30 por dia por /24 (ou /64);
  - teto bruto de 30 tentativas por hora antes do desafio.
- **Simultaneidade:** no máximo 3 testes ao mesmo tempo, com espera de até 5 s antes de `TRIAL_BUSY`.
- **Custo de IA:** finalidade `trial` com teto de **US$ 0,50 por dia**, fora do orçamento mensal dos clientes. Medido:
  cerca de US$ 0,0006 por teste.
- **Arquivo:** .docx com até 300 partes, 15 MB por parte e 25 MB no total. PDF só pelo pdfconv, até 10 páginas.
  No máximo 300 achados por teste e 30 por parágrafo.
- **Token:** 32 bytes, guardado só como hash, 404 uniforme. Mascarado no log de acesso (`app/core/logging.py`).
- **Navegador:** CSP com nonce em `src/proxy.ts`. A armadilha imita um teste real que falhou.

Já corrigidas no `e11aa36`:
- **QA-6:** testes órfãos agora têm heartbeat (`trials.heartbeat_at`) e são encerrados; `TRIAL_BUSY` não conta mais no
  limite por hora.
- **QA-5:** o upload autenticado tem teto de 60 MB descomprimidos e 1.000 partes.
- **Armadilha:** valida o arquivo antes de decidir.
- **Esperas:** no máximo 10 simultâneas antes de `TRIAL_BUSY`.
- **Teste intermitente do pdfconv:** o servidor agora drena o corpo ao recusar.

No `03db4ed` entrou também o aviso de teste vencido ou já guardado em `/register?trial=` e `/login?trial=`, com E2E.

Verificação feita pelo engenheiro na sessão local:
- **Testes do backend:** a suíte completa passou pela última vez antes de QA-5, QA-6 e do aviso. Depois disso rodaram
  só os testes das partes tocadas, todos verdes. **Rode a suíte completa primeiro.**
- **Migrations:** `0009` e `0010` conferidas no Postgres 17 (upgrade, check, downgrade, upgrade).
- **E2E:** trial, client-request e landing verdes. `individual.spec` só falha sem LibreOffice (sem PDF), não por causa
  da sprint.
- **IA real:** custo da sprint US$ 0,00; tudo rodou com IA falsa.

### B — Link para o cliente preencher (D39): em andamento

Requisitos: spec, seção B. O commit WIP `e11aa36` traz:
- migration `0010` (`client_requests` + `trials.heartbeat_at`), conferida no Postgres 17;
- rotas do profissional e rotas públicas, com envio validado;
- `fill-files` com até 3 leituras de IA por link;
- telas: diálogo "Pedir dados", "Respostas recebidas" com contador no menu, página pública `/r/{token}`;
- fotos endurecidas e rota `/info` do pdfconv (conta as páginas);
- D39 em `docs/DECISIONS.md`, `docs/API.md`, README e `.env.example`;
- E2E `frontend/e2e/client-request.spec.ts`, verde.

Falta na B:
- rodar a suíte completa (no WIP só rodaram os arquivos tocados);
- passar por **QA e segurança**: estresse do link público, enumeração do token, upload pelo link, custo de IA por
  link, XSS em `/r/{token}`;
- trocar o xfail placeholder de `/r/{token}` em `test_security_phase2.py` por testes reais.

Requisitos de segurança combinados para a B (conferir na revisão):
- Página pública `/r/{token}`: token só como hash, máscara no log (já coberta), CSP com nonce e nenhum
  `dangerouslySetInnerHTML`.
- Foto pelo link: JPEG aberto com `draft()`; PNG e WEBP com no máximo 16 Mpx (hoje o limite geral é 50 Mpx; uma foto
  de 48 Mpx gasta ~290 MB na API); um arquivo por vez.
- PDF: contar as páginas **pelo pdfconv**, no máximo 10 para a IA ler. **Nunca** abrir PDF de fora dentro da API.
- Multipart lido à mão sempre capturando `MultipartParseError` (400 `FORM_INVALID`).
- Regressão que espera a B: `test_security_phase2.py` tem um xfail placeholder para `/r/{token}`.

### C — Assinatura eletrônica (D40): a fazer

Está tudo no spec, seção C:
- interface comum de provedor;
- adaptadores testados com `httpx.MockTransport`;
- credenciais por espaço de trabalho criptografadas com Fernet (`ENCRYPTION_KEY`);
- webhook `POST /api/v1/signatures/webhook/{provedor}/{chave}` com verificação de assinatura e idempotência;
- consulta periódica como reserva;
- PDF assinado guardado como arquivo da geração (tipo `signed`);
- gov.br: pesquisar se há API para empresa privada; se não houver, fluxo assistido (Assinador ITI + upload +
  verificação PAdES no pdfconv + link para `validar.iti.gov.br`).

Requisitos de segurança já definidos para a C (OBR-10 a OBR-13 em `docs/SEGURANCA_SPRINT.md`): webhook verificado e
idempotente, credenciais criptografadas, anti-SSRF nas URLs dos provedores.

Documentação já levantada (confira de novo antes de codificar):
- **ZapSign:** `POST /api/v1/docs` com Bearer. O webhook **não tem HMAC**, só um cabeçalho próprio configurável:
  use o segredo nesse cabeçalho mais a chave aleatória na URL e confirme o status consultando a API.
- **Clicksign v3:** `sandbox.clicksign.com/api/v3`, formato JSON:API. O webhook vem com `Content-Hmac: sha256=<hex>`
  (HMAC-SHA256 do corpo).

O Daniel precisa criar contas sandbox e tokens: ZapSign, Clicksign, D4Sign, Autentique, DocuSign (integration key e
conta demo) e Adobe Acrobat Sign.

Também ficou de fora: o "aceitar todas as sugestões" ainda insere campo por campo. Dá para usar o caminho em lote
`nodes.apply_fields`, como já faz a prévia do teste.

## 3. Depois da sprint (combinado com o Daniel)

1. Rodar a suíte inteira (`ruff check app tests`, `pytest -q`, `npx tsc --noEmit -p .`, eslint, E2E no Edge).
2. Reconstruir o stack Docker e entregar ao Daniel um relatório com o que ele precisa fornecer:
   - chaves do Turnstile de produção;
   - contas sandbox dos provedores de assinatura;
   - `TRUSTED_PROXIES` restrito no servidor.
3. Checklist de implantação em `docs/SECURITY_AND_LGPD.md`: `TRUSTED_PROXIES` restrito; `TRUSTED_PROXY_HOPS=2` com
   proxy de borda; a trava da reserva de orçamento só existe no Postgres.

## 4. Outras pendências conhecidas (fora da sprint)

Fidelidade de PDF:
- ligar a heurística do modo automático (`_looks_like_form` em `backend/app/docx_engine/pdf_import.py` hoje retorna
  `False`; plano: parte de prosa ≥ 0,4 → fluxo, senão layout exato);
- opção de modo de PDF no upload;
- relatório `docs/FIDELIDADE`.

Resultados no corpus: PDF geral 49% → 60% no modo fluxo; 93,5% no layout forçado.

## 5. Regras que valem sempre

- **Segredos nunca no repositório, no log ou no chat.** Local: OpenRouter em `~/.minuta/openrouter.key`, Stripe
  teste em `~/.minuta/stripe-test.key`, `TYPESAFE_API_KEY` no `.env` da raiz (gitignored). Na nuvem esses arquivos
  **não existem**: configure como variáveis de ambiente ou secrets do ambiente da sessão, ou trabalhe com IA falsa.
- **IA real custa dinheiro de verdade** (a conta OpenRouter tem poucos dólares). Testes automáticos e de estresse
  usam IA falsa (`scripts/fake_openrouter.py` ou `httpx.MockTransport`). Modelos: `anthropic/claude-haiku-5.5` para
  detectar campos e `google/gemini-2.5-flash` para preencher e revisar (`OPENROUTER_ASSIST_MODEL`). Não mande
  `temperature` (dá 404 com `require_parameters`).
- Documentos pessoais do Daniel (pasta Downloads) só podem ser processados localmente. Nunca mandar para IA, nunca
  commitar.
- Commits pequenos em pt-BR, terminando com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Adicionar
  arquivos um a um. Push só quando o Daniel pedir.
- Migrations em `backend/migrations/versions/`, em ordem: `0009` (A), `0010` (B), `0011` (C).
- Login de demonstração: `demo@docfeito.com.br` / `demo12345`. As chaves de localStorage continuam `minuta:*` de
  propósito.

## 6. Como rodar

Sem Docker, que é o modo mais simples na nuvem:

```bash
# backend/ (Python 3.12, deps em backend/requirements*.txt ou pyproject)
export DATABASE_URL=sqlite:///./data/dev.db STORAGE_BACKEND=local JOB_BACKEND=thread PDF_CONVERTER=none \
  APP_ENV=development PUBLIC_WEB_URL=http://localhost:3000 ALLOWED_ORIGINS=http://localhost:3000 SEED_DEMO_PASSWORD=demo12345
python -m uvicorn app.main:app --port 8000 --no-proxy-headers   # cria as tabelas no SQLite
python -m app.cli seed                                           # depois que a API subiu
# frontend/
API_INTERNAL_URL=http://127.0.0.1:8000 npx next dev --webpack -p 3000
```

O atalho do QA, `scripts/stack_local.sh up|down|status|restart-api`, sobe a IA falsa, a API e o front de uma vez.

Com Docker, na máquina do Daniel:
- stack `minuta` em 3000/8100: `docker compose up -d --build`;
- IA: `docker-compose.ai.yml`;
- Stripe teste: `docker-compose.billing.yml`.

Testes:
- `cd backend && ruff check app tests && pytest -q`;
- `cd frontend && npx tsc --noEmit -p . && npx playwright test`. Localmente o E2E usa o Edge (`E2E_CHANNEL=msedge`);
  na nuvem, use o Chromium do Playwright.
