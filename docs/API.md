# API

Referência interativa (OpenAPI/Swagger): **`http://localhost:8100/api/docs`** · esquema: `/api/openapi.json`.
Prefixo: `/api/v1`. Pelo navegador use sempre a mesma origem do web (`http://localhost:3000/api/v1/...`).

## Convenções
- **Autenticação**: cookie `minuta_session` (HttpOnly). Métodos `POST/PUT/PATCH/DELETE` exigem o cabeçalho `X-CSRF-Token` (valor do cookie `minuta_csrf`, também devolvido em `/auth/me`).
- **Erros** (sempre o mesmo envelope):
  ```json
  { "error": { "code": "BATCH_INVALID_ROWS", "message": "…", "request_id": "…", "details": {…} } }
  ```
  `401` sem sessão · `403` CSRF/origem/permissão · `404` inexistente **ou de outro workspace** · `409` conflito (`STALE_REVISION`, `DUPLICATE_FIELD_NAME`, `ALREADY_CURRENT`…) · `410` arquivo expirado · `422` validação · `429` limite/rate-limit · `503` conversor de PDF ou preparo do modelo indisponível (`TEMPLATE_UNAVAILABLE`).
- **Idempotência**: `POST /generators/{id}/generate`, `/batches` e `/jobs/{id}/repeat` aceitam o cabeçalho `Idempotency-Key`. Repetir a chave devolve o **mesmo job** (`200` + `Idempotent-Replayed: true`) em vez de criar outro.
- **Paginação**: `page`, `page_size` → `{ items, total, page, page_size }`.
- **Valores de linha** (formulário/lote) trafegam como **texto de exibição pt-BR** (`"1.234,56"`, `"21/09/2026"`, `"529.982.247-25"`) ou tipos JSON nativos; o servidor normaliza e valida (formato canônico só existe no servidor).
- Todo `X-Request-ID` recebido é devolvido e aparece nos logs.

## Autenticação e conta
| Método | Rota | |
|---|---|---|
| POST | `/auth/register` | cria usuário + workspace (`owner`) e abre sessão |
| POST | `/auth/login` · `/auth/logout` | |
| GET | `/auth/me` | usuário, workspace atual, papel, limites, `csrf_token` |
| POST | `/auth/forgot-password` · `/auth/reset-password` | resposta uniforme; token de 1 h |

## Geradores
| Método | Rota | |
|---|---|---|
| GET/POST | `/generators` | lista (`q`, `status: archived`, `sort`, paginação) / cria |
| GET/PATCH/DELETE | `/generators/{id}` | DELETE = exclusão lógica; PATCH aceita `name`, `description`, `filename_pattern` |
| POST | `/generators/{id}/duplicate` · `/archive` · `/unarchive` · `/pin` · `/unpin` | fixar traz o gerador para o topo do painel |
| GET | `/dashboard` | totais, documentos no mês, em andamento/erro, recentes (fixados primeiro) |

## Modelo (template)
Sem rascunho/publicação: `document_generators.current_version_id` é a versão em uso; salvar no editor já vale para a próxima geração.

| Método | Rota | |
|---|---|---|
| POST | `/generators/{id}/template` | upload `.docx` **ou PDF digitado** (multipart `file`): valida, parseia (PDF vira .docx antes, ver [D28](DECISIONS.md)), vira a versão atual na hora, enfileira análise. Recusas de PDF: `NOT_A_PDF`, `PDF_SCANNED` (digitalizado), `PDF_TEXT_UNREADABLE`, `PDF_TOO_MANY_PAGES`, `PDF_TIMEOUT`, `PDF_CONVERSION_FAILED`; `ENCRYPTED` para PDF com senha. A versão traz `source_format` (`docx`\|`pdf`) |
| GET | `/generators/{id}/editor` | documento (ProseMirror JSON), campos, versão atual, avisos (`404` se nenhum arquivo foi enviado ainda) |
| PUT | `/generators/{id}/editor/content` | `{revision, doc}`; `409 STALE_REVISION` se a revisão mudou |
| GET | `/generators/{id}/versions` · POST `…/versions/{vid}/restore` | histórico (a mais recente é a atual) / restaurar uma versão antiga como nova versão atual |
| GET | `/generators/{id}/form` | campos + documento para o formulário/prévia da versão atual |

## Campos
| Método | Rota | |
|---|---|---|
| GET/POST | `/generators/{id}/fields` | lista / cria (`label`, `type`, `options`, `config`…) |
| PUT | `/generators/{id}/fields/order` | `{ids:[…]}` ordem do formulário |
| PATCH/DELETE | `/fields/{fid}` | DELETE `?occurrences=keep_text\|remove_text` |
| PUT | `/fields/{fid}/options` | substitui a lista (recusa duplicatas por rótulo/valor) |

Tipos: `text_short, text_long, number, currency, date, cpf, cnpj, cep, email, phone, select, yes_no, checkbox`.

## Sugestões
`GET /generators/{id}/suggestions` (agrupadas por texto+nome; rótulo/nome já vêm numerados quando há mais de um valor distinto do mesmo campo-base, ex. "CNPJ 1"/"CNPJ 2" — ver D26) · `POST …/suggestions/analyze {force}` · `POST …/suggestions/accept-all {min_confidence}` · `POST /suggestions/{sid}/accept {name,label,type,apply_to_all}` (uma sugestão `select` com lista pronta, ex. mês, cria o campo já com todas as opções, não só o texto encontrado) · `POST /suggestions/{sid}/ignore`.

## Geração
| Método | Rota | |
|---|---|---|
| POST | `/generators/{id}/generate` | `{values, format: docx\|pdf\|both, filename_pattern}` → job (202) |
| POST | `/batch/identify` | `{headers, rows (≤50), generator_id?}` → modelo provável para uma **tabela colada**, com o mapeamento coluna → campo (`status`: `exact`\|`probable`\|`weak`\|`none`). Sem linha de títulos (`header_looks_like_data: true`) só o casamento local por conteúdo roda — nada vai ao classificador externo (ver D28) |
| POST | `/generators/{id}/batch/validate` | `{rows}` → erros por linha/campo (autoridade de validação) |
| POST | `/generators/{id}/batches` | `{rows, format, only_valid, filename_pattern, idempotency_key}` → job |
| GET | `/generators/{id}/batch/template.xlsx` | planilha-modelo com listas/validações e aba de instruções |
| POST | `/generators/{id}/batch/imports` | envia `.xlsx`/`.csv` → colunas, amostra, **mapeamento sugerido**, campos (`id`, `options` para `select` — usado pra oferecer adicionar um valor novo à lista, ver D26) |
| POST | `/generators/{id}/batch/imports/{iid}/apply` | `{mapping:[campo\|null,…]}` → linhas + validação |

## Jobs, histórico e downloads
`GET /jobs` (filtros `kind`, `status`, `generator_id`) · `GET /jobs/{id}` · `GET /jobs/{id}/items` · `POST /jobs/{id}/repeat` · `POST /jobs/{id}/cancel` · `POST /files/{fid}/link` → `{url, expires_in}` · `GET /downloads/{token}` (stream; exige sessão e o mesmo usuário/workspace do link).

Status de job: `queued → processing → succeeded | partial | failed | cancelled` (após uma falha transitória ou a queda de um worker o job pode voltar de `processing` para `queued` antes de ser retomado; o progresso já feito é mantido). Status de item: `pending, processing, succeeded, failed, skipped`.

## Kits de documentos
Agrupa geradores existentes (com `.docx` já enviado) atrás de um formulário só, para variáveis em comum (nome, CPF, endereço…). Ver [D24](DECISIONS.md).

| Método | Rota | |
|---|---|---|
| GET/POST | `/kits` | lista (`q`, `status: archived`, `sort`, paginação) / cria (`name`, `description`) |
| GET/PATCH/DELETE | `/kits/{id}` | |
| POST | `/kits/{id}/archive` · `/unarchive` · `/pin` · `/unpin` | |
| GET/POST | `/kits/{id}/items` | lista documentos do kit / adiciona um gerador (`{generator_id}`) |
| DELETE | `/kits/{id}/items/{item_id}` | remove o documento do kit (o gerador em si não é afetado) |
| PUT | `/kits/{id}/items/{item_id}/mapping` | `{mapping: {campo_do_kit: campo_do_gerador\|null}}`; recusa tipos incompatíveis (`TYPE_MISMATCH`) |
| POST | `/kits/{id}/auto-detect` | agrupa campos entre ≥2 documentos em novos `kit_fields` (ou atualiza o mapeamento dos existentes); com `TYPESAFE_API_KEY` configurada, classifica por papel/atributo semântico (D25), senão só por rótulo quase idêntico (D24) — resposta inclui `provider: "typesafe" \| "similarity"` |
| GET/POST | `/kits/{id}/fields` | lista / cria um campo compartilhado (`label`, `type`, `options`…) |
| PATCH/DELETE | `/kit-fields/{fid}` | tipo não muda depois de criado |
| PUT | `/kit-fields/{fid}/options` | substitui a lista de opções |
| GET | `/kits/{id}/form` | kit + campos compartilhados + documentos membros (com os campos "só daquele documento") — usado pela tela de uso e de edição |
| POST | `/kits/{id}/runs` | `{values, member_values, format, filename_pattern, idempotency_key}` → cria um `generation_jobs` por documento membro (202); `Idempotency-Key` aceito |
| GET | `/kit-runs` | lista (`kit_id`, paginação) |
| GET | `/kit-runs/{id}` | status **derivado** dos jobs membros (`queued/processing/succeeded/partial/failed`), arquivos (ZIP consolidado + relatório CSV, construídos na primeira leitura após o fim) |

## IA no preenchimento (D33)
Só responde com `EXTERNAL_AI_ENABLED=true` e a chave da OpenRouter configurada. Se não, devolve 409 `AI_DISABLED`. Cada chamada conta 1 uso na cota mensal do plano. Erros possíveis (409): `AI_QUOTA_EXCEEDED`, `AI_BUDGET_EXHAUSTED`, `AI_CALL_TOO_EXPENSIVE` e `AI_*` de indisponibilidade.

| Método | Rota | |
|---|---|---|
| GET | `/assist/status` | `{enabled, actions_used, actions_limit}`. A interface só mostra os botões de IA com `enabled: true` |
| POST | `/generators/{id}/assist/fill` | `{text}` (até 8.000 caracteres usados) → `{values, invalid, evidence, missing, truncated}`. `values` traz só o que tem evidência no texto. `invalid` lista os valores que não passam na validação do tipo; eles vão mesmo assim, marcados |
| POST | `/kits/{id}/assist/fill` | igual, com os campos em comum do kit |
| POST | `/generators/{id}/assist/fill-files` | multipart `files` (1 a 4 fotos JPG/PNG/WEBP ou PDF, 8 MB cada) → `{values, invalid, evidence, missing, documents}`. Fotos regravadas sem metadados antes de sair (JPEG decodificado já reduzido; PNG/WEBP até 16 Mpx); PDF não é aberto na API: as páginas são contadas no conversor isolado, até 10 (D37, D39). Recusas: `AI_FILE_TYPE`, `AI_FILE_INVALID`, `AI_TOO_MANY_FILES`, `FILE_TOO_LARGE`, `AI_PDF_TOO_MANY_PAGES`, `AI_PDF_DISABLED` (sem conversor isolado) |
| POST | `/kits/{id}/assist/fill-files` | igual, com os campos em comum do kit |
| POST | `/generators/{id}/assist/review` | `{values}` → `{issues: [{field, label, severity: alta\|media\|baixa, message}]}`, no máximo 8. Não altera nada |

## Cobrança (D34)
| Método | Rota | |
|---|---|---|
| GET | `/billing/plans` | **público**: planos (`plans.json`), moeda e `checkout: {card, pix}` disponíveis neste ambiente |
| GET | `/billing` | plano efetivo, assinatura, uso do mês (`docs_this_month`, `ai_actions_this_month`, `models`) e limites |
| POST | `/billing/checkout` | `{plan: profissional\|escritorio, cycle: mensal\|anual, method: card\|pix}` → `{url}` do Checkout da Stripe. Só o proprietário. `BILLING_NOT_CONFIGURED`, `BILLING_HAS_SUBSCRIPTION` |
| POST | `/billing/portal` | → `{url}` do portal do cliente (assinatura no cartão) |
| POST | `/billing/webhook` | só para a Stripe: sem sessão, valida `Stripe-Signature` (HMAC, 300 s) e é idempotente por `event.id` |

## Teste grátis na landing (D38)
Rotas **públicas** (sem sessão) sob `/public/trials`. O token tem 32 bytes aleatórios e só o hash fica no servidor; token errado, vencido (1 hora) ou já guardado respondem igual: `404 TRIAL_NOT_FOUND`.

| Método | Rota | |
|---|---|---|
| GET | `/public/trials/config` | `{enabled, max_mb, max_pages, accepts_pdf, turnstile_site_key, ttl_minutes}` |
| POST | `/public/trials` | multipart `file` (.docx ou PDF digitado), `turnstile_token` (com o Turnstile ligado) e `website` (armadilha: vazio) → `202 {token, status: "processing", expires_at}`. Recusas: `411 LENGTH_REQUIRED`, `413 FILE_TOO_LARGE` (pelo `Content-Length`, antes de ler), `422` (`EMPTY_FILE`, `TRIAL_FILE_TYPE`, `PDF_IMPORT_DISABLED`, `ZIP_BOMB`…), `403 TRIAL_CHALLENGE_FAILED`, `429 TRIAL_RATE_LIMITED` (3/h e 10/dia por IP, 30/dia por /24 ou /64, contando tentativas) e `429 TRIAL_BUSY` (testes simultâneos), `503 TRIAL_DISABLED` |
| GET | `/public/trials/{token}` | `{status: queued\|processing\|done\|failed, filename, format, expires_at, ai: ai\|local\|budget\|rules, error, result: {doc, fields: [{id, name, label, type, sample, count}], warnings, stats}}`. Consultar a cada ~1,5 s (120/min por IP). Falhas: `TRIAL_TOO_LONG`, `PDF_SCANNED`, `DOCX_PARSE_FAILED`, `EMPTY_DOCUMENT`, `TRIAL_FAILED`… |
| POST | `/trials/{token}/claim` | **com sessão**: o documento do teste vira modelo da conta, com as sugestões → `201 {generator_id, next}` (`next` = etapa Campos). `409 TRIAL_NOT_READY`, `429 GENERATOR_LIMIT` (o teste continua disponível) |

## Link para o cliente preencher (D39)
Com sessão (profissional):

| Método | Rota | |
|---|---|---|
| POST | `/generators/{id}/client-requests` · `/kits/{id}/client-requests` | `{fields?, message?, expires_days (1–30, padrão 7), allow_photos, prefill?, prefill_mode: hidden\|readonly\|editable}` → `201 {id, state, url, share_text, …}`. O `url` (com o token) aparece **só aqui**. `REQUEST_UNKNOWN_FIELD`, `REQUEST_NO_FIELDS`, `REQUEST_LIMIT` |
| GET | `/client-requests` | `generator_id`, `kit_id`, `state: open\|answered\|expired\|cancelled`, paginação → itens sem os valores |
| GET | `/client-requests/summary` | `{new_answers}` (respostas ainda não abertas — o contador do menu) |
| GET | `/client-requests/{id}` | detalhe **com os valores**; abrir trava a resposta (o cliente não altera mais) |
| POST | `/client-requests/{id}/cancel` · `/used` | cancelar (apaga a resposta) · marcar como usada depois de gerar (apaga os dados do pedido) |

Públicas (o cliente, sem sessão). Token errado, cancelado ou de outro espaço: `404 REQUEST_NOT_FOUND`.

| Método | Rota | |
|---|---|---|
| GET | `/public/requests/{token}` | `{state: open\|answered, workspace, document, message, fields, prefill_mode, prefill, values, photos: {allowed, reads_left}, expires_at}` ou `{state: expired\|closed}` |
| POST | `/public/requests/{token}` | `{values}` → `{state: "answered", submissions}`; `422 REQUEST_INVALID_VALUES` com `details.field_errors`; `409 REQUEST_CLOSED` (vencido ou já aberto pelo profissional) |
| POST | `/public/requests/{token}/fill-files` | multipart `files` (até 3; JPG/PNG/WEBP ou PDF até 10 páginas; 8 MB cada) → `{values, invalid, evidence, missing, documents, reads_left}`. `409 REQUEST_PHOTOS_DISABLED`, `429 REQUEST_READS_USED` (3 por link), `400 FORM_INVALID` |

## Operação
`GET /health` (liveness) · `GET /ready` (banco + conversor) · `GET /metrics` (Prometheus).
