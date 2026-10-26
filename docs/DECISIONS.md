# Decisões técnicas (ADRs resumidos)

Formato: **decisão → motivo → alternativas rejeitadas → consequências/concessões.**
Este arquivo foi escrito *antes* da implementação e é atualizado quando algo muda.

---

## D01 — Monólito modular, sem microserviços
- **Decisão:** um backend FastAPI dividido em módulos (`auth`, `generators`, `templates`, `fields`, `suggestions`, `generation`, `batches`, `history`, `downloads`, `audit`) + um worker que reutiliza o mesmo código.
- **Motivo:** o produto ainda não tem carga que justifique fronteiras de rede. Módulos com serviços puros e adaptadores (armazenamento, PDF, IA, fila, notificações) permitem dividir depois sem reescrever regras.
- **Rejeitado:** microserviços por domínio; Kubernetes (fora do escopo pedido).

## D02 — DOCX: original imutável + modelo de blocos + compilação com tokens
Este é o maior risco técnico do MVP, por isso a decisão é detalhada.
- **Decisão:**
  1. O `.docx` enviado é guardado **imutável** (SHA-256, nome interno aleatório).
  2. O servidor extrai um **modelo de blocos**: cada parágrafo (corpo, células de tabela, cabeçalhos, rodapés) recebe uma chave estável (`body/p3`, `body/t1/r2/c1/p1`, `header1/p1`). O conteúdo inline vira texto com marcas (negrito/itálico/sublinhado/tachado), *átomos* opacos (imagens, campos complexos, hyperlinks…) e nós de campo.
  3. O editor edita esse modelo (TipTap). A **posição de um campo** é armazenada como âncora: chave do bloco + offsets normalizados + trecho original + contexto antes/depois + versão.
  4. **Compilação:** só os parágrafos *modificados* (texto editado, marca alterada ou campo) são reconstruídos a partir do original, com mapeamento caractere→run (via `difflib`) para herdar a formatação. Cada ocorrência de campo vira **um único run** com um token único (`⟦F:<nonce>:<nome>⟧`). Parágrafos não modificados permanecem byte a byte iguais.
  5. **Renderização:** troca dos runs-token pelos valores formatados. Como cada ocorrência já é um run isolado, não há substituição por string atravessando runs — o problema clássico do Word.
- **Por que não substituir `{{placeholder}}` direto no XML:** o Word fragmenta texto em vários runs (revisão ortográfica, formatação parcial). Esse é justamente o caso de "João da Silva" com "Jo" e "ão da Silva" em runs diferentes.
- **Rejeitado:**
  - *DOCX → HTML (mammoth) → DOCX*: perde estilos, cabeçalhos/rodapés, numeração e layout.
  - *`docxtpl`/Jinja no DOCX*: exige que o usuário escreva `{{ }}`; o produto existe para evitar isso. Só faria sentido para modelos escritos à mão.
  - *Guardar o documento inteiro como JSON do editor e gerar DOCX do zero*: perda de fidelidade garantida.
- **Concessões honestas:** parágrafos alterados perdem `w:ins/w:del` (alterações rastreadas são aceitas/descartadas) e a estrutura de tabelas não é editável no MVP. Elementos avançados (imagem, campo complexo do Word, sdt) são preservados como átomos, não editáveis.

## D03 — Editor: TipTap/ProseMirror com nó `field` atômico
- Extensão própria `field` (inline, atom) renderizada como chip com ícone por tipo (não depende só de cor), com nome/tipo/estado no `title` e no popover.
- **Modelo de offsets comum** cliente/servidor: o texto de um bloco é a concatenação de texto + `sample` do campo (texto original que ele substituiu) + `U+FFFC` por átomo + `\n` por quebra. Isso garante que âncoras calculadas no servidor coincidam com as do editor.
- Menu flutuante próprio (posicionado por `coordsAtPos`) + atalho de teclado (`Ctrl+Shift+F`) + botão no painel — acessível sem mouse.
- Estrutura de tabelas e criação/remoção de parágrafos: parágrafos novos (Enter) são suportados e clonam o `pPr` do vizinho; tabelas são estruturalmente bloqueadas.
- **Rejeitado:** Slate/Lexical (menos maduros para nós inline atômicos com NodeView React); CKEditor/OnlyOffice (licença/peso).

## D04 — Grade do lote: `@tanstack/react-virtual` + camada própria
Avaliadas: **AG Grid Community**, **Glide Data Grid**, **TanStack Table + Virtual**.
- AG Grid Community: seleção de intervalo e clipboard de intervalo são *Enterprise*. Sem isso, "colar do Excel" e "preencher para baixo" viram gambiarra.
- Glide Data Grid: excelente desempenho (canvas), mas acessibilidade limitada, editores customizados (data/dropdown) são sobreposições, E2E difícil (não há DOM por célula) e ruído de compatibilidade com React 19.
- **Escolha:** DOM real (`role="grid"`) virtualizado por linha com `@tanstack/react-virtual`; seleção retangular, colar TSV, copiar, `Ctrl+D`, editores nativos (`<input>`, `<select>`, `type=date`, `checkbox`). Sem TanStack Table: o modelo de linhas é simples e o filtro/busca é trivial.
- Custo: ~600 linhas próprias, mas com controle total sobre máscara/validação por célula, foco e testes Playwright.

## D05 — Fila: Dramatiq (não Celery)
- Retries com `retry_when` seletivo (só falhas transitórias), dead-letter embutido no broker Redis, middleware Prometheus, `StubBroker` para testes, funciona em Windows (dev). Celery é mais pesado e o prefork não roda em Windows.
- **Abstração `JobQueue`** com três backends: `dramatiq` (produção/compose), `thread` (dev sem Docker) e `sync` (testes). A função `run_generation_job(job_id)` é a mesma nos três; ela é **idempotente** (itens já concluídos são pulados). A recuperação após queda do worker não depende do redelivery do Dramatiq — ver D22.

## D06 — Sessão: cookie opaco + tabela de sessões + CSRF duplo-cookie
- Cookie `HttpOnly`, `SameSite=Lax`, `Secure` em produção; valor aleatório de 256 bits, guardado **apenas como hash** no banco (permite revogação e expiração deslizante). CSRF: cookie legível `csrf` + cabeçalho `X-CSRF-Token` em métodos inseguros, e checagem de `Origin`.
- API continua *sem estado em memória*: qualquer instância valida a sessão pelo banco.
- **Rejeitado:** JWT (revogação difícil, armazenamento no navegador exposto a XSS).
- Preparado para login social: `users` não exige senha (`password_hash` nulo) e há tabela `auth_identities`.

## D07 — SQLAlchemy 2 síncrono
- Endpoints `def` (executados em threadpool) + `psycopg`. Mais simples e robusto que async para um monólito CRUD + I/O bloqueante (zip/XML/LibreOffice) que precisa de threads de qualquer forma. Migração para async fica localizada nos repositórios.

## D08 — Portabilidade de banco: PostgreSQL em produção, SQLite nos testes rápidos
- Tipos portáveis (`Uuid`, `JSON().with_variant(JSONB)`, `String` + `CHECK` em vez de enum nativo).
- Suíte roda em SQLite por padrão (rápida, sem infraestrutura) e em PostgreSQL quando `TEST_DATABASE_URL` está definido (usado no compose). Migrations Alembic são aplicadas no compose.
- JSONB **apenas** onde a estrutura é realmente variável: conteúdo inline de um bloco, valores de uma linha do lote, sugestões brutas da IA, metadados de auditoria.

## D09 — Downloads: token HMAC curto servido pela API
- `POST /files/{id}/link` devolve URL com token assinado (HMAC, ~5 min). A API valida workspace + expiração do arquivo (`expires_at`) e faz stream do storage. Vantagem: funciona igual com MinIO/S3/local, sem expor o endpoint do storage ao navegador, e audita cada download.
- **Rejeitado (por ora):** URL pré-assinada do S3 direta (melhor para arquivos grandes; ver ROADMAP).

## D10 — IA: interface + provedor local explícito
- `AIFieldSuggestionProvider` com `LocalHeuristicProvider` (usado quando **não há chave**; a UI informa "sugestões locais, IA externa não configurada") e `AnthropicMessagesProvider` (URL/modelo/chave por variáveis de ambiente, timeout, retry limitado só para 429/5xx/timeout, truncagem por caracteres).
- Resposta da IA validada por schema Pydantic; qualquer campo inválido é descartado.
- Resultado cacheado por `(workspace, sha256 do arquivo, provider, versão do prompt)` em `ai_analysis_runs`. Consumo (tokens, duração, nº de caracteres) é registrado; **conteúdo não é logado**.
- A IA nunca altera o modelo: só gera sugestões que o usuário aceita.

## D11 — PDF: LibreOffice headless, sem fallback falso
- `PdfConverter` (adapter) com `LibreOfficeConverter`: perfil isolado por processo, timeout, verificação do arquivo de saída (`%PDF-`), conversão em **lotes de N arquivos por processo** (uma invocação carrega o LO uma vez — essencial para 1.000 documentos) com fallback item a item para isolar falhas.
- Se o binário não existe, a API responde `PDF_CONVERTER_UNAVAILABLE` (503) e o DOCX continua funcionando. **Não existe conversor "de mentira".**

## D12 — Multi-tenant
- `workspace_id` em toda tabela de domínio; toda consulta passa por repositórios/serviços que exigem `workspace_id`. IDs são UUID v4 (não sequenciais). Recurso de outro workspace responde **404** (não 403), para não confirmar existência.
- Papéis `owner`/`member`; a UI de convites fica para depois.
- Teste automatizado com dois workspaces cobre todos os endpoints de leitura/escrita e download.

## D13 — Valores canônicos + vetores de teste compartilhados
- O servidor é a autoridade de normalização/validação; o cliente replica para feedback imediato. Formato canônico: texto → str; número/moeda → decimal em string (`"1234.50"`); data → ISO; CPF/CNPJ/CEP/telefone → só dígitos; e-mail → minúsculo; sim/não e checkbox → boolean; lista → **valor interno** da opção.
- `shared/field-vectors.json` é consumido por pytest **e** vitest para impedir divergência.

## D14 — Versionamento do modelo (revisado — ver D23)
- ~~Cada gerador tem uma versão rascunho editável e no máximo uma publicada imutável.~~ Substituído: não existe mais rascunho/publicação — ver D23. Histórico e geração continuam referenciando `template_version_id`.

## D15 — Idempotência
- `Idempotency-Key` (header) / `idempotency_key` (body) + `UNIQUE(workspace_id, idempotency_key)` em `generation_jobs`. Repetir a requisição devolve o mesmo job. O executor do job também é idempotente (itens `succeeded` são pulados; ZIP é regerado).

## D16 — Versões de linguagem
- Alvo de produção: **Python 3.12** (imagem Docker). Desenvolvimento local nesta máquina: 3.14; o código evita recursos exclusivos de 3.13+ e os testes rodam nas duas. Node 24 / Next.js 16 / React 19 / Tailwind 4.

## D17 — Frontend
- Next.js App Router, majoritariamente *client components* (app autenticado). `next.config` faz *rewrite* de `/api/*` para o backend → mesma origem, cookies simples, sem CORS.
- Radix UI + componentes próprios com tokens CSS (`--color-*`, `--radius-*`, `--shadow-*`); não usamos o CLI do shadcn para manter a árvore de dependências pequena. Tema escuro estruturado por tokens (`[data-theme=dark]`), não obrigatório.
- Estado de servidor: TanStack Query. Formulários: React Hook Form + Zod (o formulário do gerador é gerado dinamicamente a partir dos campos).

## D18 — Entrada PDF
- PDF é apenas **formato de saída**. Existe a interface `TemplateSourceParser` (hoje só `DocxParser`) como ponto de extensão. Nenhuma tela anuncia edição de PDF.

## D19 — Limites por workspace
- `workspaces.limits` (JSON, com defaults em configuração): geradores, linhas por lote, tamanho de upload, documentos/mês. Verificados nos serviços — nunca só no cliente.

## D20 — Retenção
- `generated_files.expires_at` (padrão 7 dias) + comando `python -m app.cli cleanup` (agendável) que remove objetos expirados e marca o registro. Downloads recusam arquivos expirados.

## D21 — Imagem do MinIO
- A MinIO não publica mais imagens no Docker Hub (`minio/minio` responde "pull access denied"). O compose usa `quay.io/minio/minio:RELEASE.2025-04-22T22-12-26Z` (tag fixa, testada). Em produção use S3 real ou o serviço gerenciado do seu provedor; nada no código depende de MinIO — só de um endpoint S3 (`S3_ENDPOINT_URL`).

## D22 — Recuperação de jobs após queda do worker (heartbeat + watchdog no banco)
- **Problema encontrado em teste real** (SIGKILL no worker no meio de um lote de 400 DOCX+PDF): o job ficou `processing` e **não foi retomado em 7 minutos**. Causa: o Dramatiq só reentrega mensagens de workers mortos numa rotina de "manutenção" que roda com probabilidade de 1 em 1000 a cada consulta ociosa (`maintenance_chance`) — a recuperação é eventual, imprevisível (o job acabou concluído bem depois) e não pode ser a garantia do produto.
- **Decisão**: a garantia vive no banco, independente do broker. `generation_jobs.heartbeat_at` é renovado a cada 10 s por uma thread do executor; um *watchdog* (thread em cada processo do worker, a cada 15 s; também na API no modo `thread`; ou `python -m app.cli requeue-stuck`) reenfileira job `processing` sem heartbeat há 60 s e job `queued` há 5 min (mensagem perdida, p. ex. Redis reiniciado sem persistência).
- **Segurança da retomada**: (1) reservar o direito de reenfileirar é um `UPDATE` condicional — com N watchdogs só um vence; (2) `claim_job` assume o job atomicamente (`queued` ou `processing` com heartbeat velho) e incrementa `attempts` — mensagem duplicada do broker vira no-op; (3) o executor antigo confere `attempts` a cada bloco e para (`_LostOwnership`) se perdeu a posse; (4) o runner continua idempotente (remove saídas parciais do item antes de refazer). Falha transitória com Dramatiq devolve o job a `queued` antes de relançar, para o retry do broker conseguir assumi-lo.
- **Trade-offs**: entrega *at-least-once* (um bloco de 20 itens em voo pode ser refeito — sem duplicar arquivos); a retomada leva ≈ 1 a 1,5 min (`JOB_STALE_SECONDS` + intervalo do watchdog); job legítimo com heartbeat parado por >60 s (banco fora do ar) pode ser retomado por outro worker, o que a checagem de posse torna inofensivo. Alternativas descartadas: subir `maintenance_chance` do Dramatiq (continua probabilístico e só resolve esse broker) e *outbox transacional* (mais peças; o watchdog cobre também a mensagem perdida).

## D23 — Sem rascunho/publicação: um gerador sempre tem uma única versão "atual", pronta para uso
- **Pedido do usuário**: simplificar o produto — esquecer a classificação rascunho/publicado; criar o gerador já deixa ele pronto; no máximo, fixar (`is_pinned`) os mais usados no topo do painel.
- **Decisão**: `document_generators.current_version_id` aponta para a `template_versions` em uso (editor, formulário, lote). Enviar um `.docx` ou restaurar uma versão do histórico troca esse ponteiro na hora — não existe mais um estado "rascunho" separado do que é usado para gerar. Editar sempre altera a versão atual diretamente (sem clonar um rascunho); não há mais um botão "Publicar" nem gate `NOT_PUBLISHED`/`NO_DRAFT`. `document_generators.status` cai para só `active`/`archived`.
- **O que ficou** (não é o que o pedido queria remover): o histórico de versões continua existindo — cada arquivo novo ou restauração gera uma linha nova em `template_versions` (nunca reaproveita `version_number`), então nada se perde e a tela "Versões" ainda mostra a lista e permite restaurar uma antiga. Isso também mantém intacto o mecanismo de concorrência otimista do editor (`revision`) e a imutabilidade dos arquivos originais/compilados por job.
- **Compilação sem estado "publicado"**: sem uma versão publicada fixa para cachear o compilado, cada criação de job (individual ou lote) chama `compile_current`, que recompila só quando o conteúdo mudou (`compiled_revision != revision`; ver `TemplateVersion.compiled_file_id`/`compiled_revision`, agora um cache, não mais "a versão publicada"). Isso repete o custo que antes só o modo de teste (rascunho) pagava — aceitável: é uma operação de texto (XML), não a conversão para PDF.
- **Achado ao testar de verdade**: a primeira versão desta mudança compilava (e gravava no storage) toda vez que um job era criado, direto na requisição HTTP — sem cache, uma falha transitória do storage nesse momento virava um erro 500 não tratado, sem criar job nenhum (regressão de confiabilidade frente ao D22/D11). Corrigido com o cache acima **e** com retentativa (`_retry`, mesmo padrão do runner) envolvendo a leitura do arquivo original e a gravação do compilado; se mesmo assim falhar, a API responde `503 TEMPLATE_UNAVAILABLE` — claro, sem criar job — em vez de um erro genérico.
- **`is_test` removido**: como não há mais "gerar com o rascunho para testar", o campo `generation_jobs.is_test` (e o parâmetro `version=published|draft` em `/generate`, `/batches`, `/form`, `/fields`, `/batch/*`) foi removido; toda geração conta na cota e no histórico.
- **Migration**: `0003_simplify_versioning.py` — para bancos existentes, `current_version_id` recebe o rascunho em edição se houver (senão a publicada, senão a mais recente); `status` "draft"/"published" vira "active". Reversível (`alembic downgrade`).
- **Fixar geradores**: `is_pinned` (booleano) substitui qualquer classificação — geradores fixados aparecem primeiro no painel e na listagem, sem afetar o que pode ser gerado.

## D24 — Kit de Documentos: reaproveitar o pipeline de geração, não duplicá-lo
- **Pedido do usuário**: agrupar vários geradores existentes que compartilham variáveis (nome, CPF, endereço…) para preenchê-las **uma única vez** e gerar todos os documentos do kit juntos, com download individual ou em ZIP.
- **Decisão — execução**: um "kit" (`document_kits`) é só uma coleção de geradores existentes (`document_kit_items`, 1 por gerador) + campos compartilhados (`kit_fields`) + um mapeamento por item (`kit_field → field` do gerador, `document_kit_items.field_mapping` JSONB). Rodar o kit (`POST /kits/{id}/runs`) cria uma linha em `kit_runs` e **um `generation_jobs` comum por documento membro** (`kind="single"`, `kit_run_id` novo FK), reaproveitando **sem nenhuma mudança** o runner, o worker, a idempotência e o watchdog de D22 — cada job de kit é indistinguível de um job individual para o executor.
- **Por que não um pipeline paralelo**: um "job de kit" próprio duplicaria toda a lógica de retomada/heartbeat/idempotência já testada em produção (D22) para um caso que é, do ponto de vista do worker, só "N jobs individuais que nasceram juntos". Reaproveitar elimina essa superfície de risco.
- **Status sem coluna própria**: `kit_runs` **não guarda status** — é sempre derivado, na leitura, dos `status` dos jobs membros (`aggregate_status`: todos `succeeded` → `succeeded`; algum `succeeded` e algum não → `partial`; nenhum `succeeded` e algum `failed` → `failed`; senão `processing`/`queued`). Mesmo padrão "cache/derivação na leitura" de `compile_current` (D23) — evita um segundo lugar para ficar dessincronizado do estado real dos jobs.
- **Arquivo gerado polimórfico**: `generated_files.job_id` virou **anulável** e ganhou `kit_run_id` (FK), com `CHECK (job_id IS NULL) != (kit_run_id IS NULL)` — o ZIP consolidado e o relatório CSV do kit são `generated_files` comuns (pendurados no `kit_run_id`, não em um job), reaproveitando o link assinado/expiração/streaming de D09 sem nenhum endpoint novo de download.
- **Correspondência de campos — dois caminhos, nunca automático "confiar cego"**:
  1. **Manual**: o usuário mapeia campo do kit → campo de cada documento pela grade de mapeamento; só aceita tipos **idênticos** (`TYPE_MISMATCH` se não bater), porque o valor trafega já validado/normalizado para aquele tipo.
  2. **Detecção automática** (`POST /kits/{id}/auto-detect`, `app/modules/kits/matching.py`): agrupa campos de **geradores diferentes** por rótulo normalizado (sem acento/pontuação) com `difflib.get_close_matches` (corte de similaridade 0,82), restrito a tipos "seguros" para fundir sem ambiguidade (texto, número, moeda, data, CPF/CNPJ/CEP/e-mail/telefone — **não** `select`/`yes_no`/`checkbox`, onde rótulos parecidos podem ter listas de opções incompatíveis), exigindo pelo menos 2 geradores distintos por grupo e nunca dois campos do mesmo gerador no mesmo grupo.
- **Limite conhecido, documentado no teste**: a detecção automática só pega nomes/rótulos **quase idênticos** entre documentos (ex.: "CPF" em ambos, ou "Nome do contratante" com um erro de digitação) — não entende sinônimos semânticos ("Nome do contratante" vs. "Nome completo" não são agrupados sozinhos por esta heurística). O mapeamento manual continua sendo o caminho garantido para qualquer par de rótulos que a heurística não reconheça. **Atualização**: um classificador semântico opcional resolve boa parte desse limite sem abrir mão da segurança — ver [D25](#d25--classificação-semântica-de-papéis-no-auto-detect-de-kits-typesafeai--jev).
- **Migration**: `0004_document_kits.py`, gerada com `alembic revision --autogenerate` contra um Postgres descartável (para não repetir o erro de nomear constraint na mão sem `op.f(...)` — ver a lição de D23/histórico) e revisada manualmente só para acrescentar o `CHECK` de exclusividade acima (autogenerate não cobre `CHECK` composto). Testada com `upgrade head` → `alembic check` (sem divergência) → `downgrade` → `upgrade` novamente.

## D25 — Classificação semântica de papéis no auto-detect de kits (TypeSafe.ai / "Jev")
- **Pedido do usuário**: o limite conhecido de D24 — auto-detect só junta rótulos quase idênticos — deveria evoluir para reconhecer o *significado* do campo (nome, CPF, "contratante" vs. "contratado"...), inclusive quando os documentos usam palavras bem diferentes para a mesma coisa.
- **Por que Choice e não geração livre de texto**: diferente do provedor de IA de D10 (que **gera** sugestões de campo a partir de texto livre do documento), aqui o problema já é fechado: cada campo candidato precisa cair numa categoria conhecida. A TypeSafe.ai (modelo "Jev") oferece exatamente essa primitiva — `Choice`, que classifica um texto contra um conjunto fixo de opções e devolve a opção + probabilidade por opção + confiança — em vez de um LLM generativo que precisaria ser convencido, via prompt, a só responder de um jeito fechado. `POST https://api.typesafe.ai/v1/systemone` (`Bearer` token), múltiplas perguntas batchadas numa chamada só (`questions`, chave → pergunta), compartilhando um `state` (aqui, a lista numerada de campos candidatos de todos os documentos do kit).
- **Duas perguntas por campo de texto livre, uma para os demais**: **papel** — `parte_a` (quem contrata/compra/outorga/empresta — descrito de forma ampla o bastante para cobrir contratante, comprador, outorgante, locador, credor, requerente…), `parte_b` (a contraparte — contratado, vendedor, outorgado, locatário, devedor…), `terceiro` (testemunha, fiador) ou `nao_e_parte` (não é uma pessoa/empresa: valor, data, objeto…) — e, só para `text_short`/`text_long` (tipos como `cpf`/`data`/`moeda` já dizem por si só que informação é), **atributo**: `nome`, `endereco`, `cargo_profissao`, `objeto` ou `outro`. Dois campos só são agrupados se baterem em **ambas** as respostas (mais o tipo, para os que não precisam de atributo) — isso é o que impede juntar "Nome do contratante" com "Nome do contratado": rótulo parecido, mas `Choice` de papel diferente.
- **Confiança mínima, não "sempre confiar"**: como `Choice` sempre devolve uma resposta (é forçado a escolher), uma classificação abaixo de `MIN_CONFIDENCE=0.6` (papel OU atributo) não é usada para agrupar por papel — mas ver o próximo item, isso não significa que o campo fica de fora do kit. Verificado contra a API real: um caso ambíguo de propósito ("CPF" sem qualificar de quem, num documento com duas partes) ficou de fora do agrupamento **por papel**, como esperado — melhor um falso negativo ali (a heurística de similaridade ainda pode resgatar) que um falso positivo (dois CPFs de pessoas diferentes virando um campo só).
- **Caminho híbrido — achado testando contra a API real, não hipotético**: a primeira versão descartava direto quem não batesse `MIN_CONFIDENCE`, o que criou uma regressão real: dois campos "Nome completo" **idênticos** (sem nenhum "do contratante" que desse contexto de papel) receberam confiança em lados opostos do corte — 0,70 e 0,51 — numa execução real contra a TypeSafe. Descartar cada um isoladamente por confiança deixava o de 0,70 **sozinho** (nenhum outro gerador confirmou o mesmo papel, grupo descartado por ter só 1 gerador) e o de 0,51 sozinho no "resto" — os dois desapareciam, uma regressão em relação à heurística pura de D24, que juntaria esse par trivialmente (rótulo idêntico). **Correção**: em vez de decidir "confiante vs. resto" por candidato antes de agrupar, o auto-detect roda o agrupamento por papel primeiro (`suggest_kit_fields_by_role`, usando todos os candidatos) e só depois calcula o que **não entrou em nenhum grupo de verdade** (`unclustered_candidates` — inclui tanto os de baixa confiança quanto os "órfãos" confiantes sem par) para rodar a heurística por similaridade nesse resto (`suggest_kit_fields` + `candidates_to_members`), fundindo os dois resultados por (rótulo normalizado, tipo) com `merge_suggestion_lists`. Coberto por teste que reproduz exatamente o caso 0,70/0,51 (`test_hybrid_recovers_identical_label_with_confidence_straddling_the_cutoff`).
- **Puramente aditivo, nunca obrigatório**: sem `TYPESAFE_API_KEY` configurada, `get_role_classifier()` devolve `None` e o auto-detect segue exatamente como em D24 (heurística local por similaridade de rótulo, `suggest_kit_fields`). Com a chave configurada, qualquer falha do classificador (rede, timeout, credencial, resposta fora do formato) levanta `RoleClassifierUnavailable`, capturada em `kits/service.py::auto_detect`, que cai de volta na mesma heurística local — mesma filosofia de degradação de D10 ("nunca quebra sem IA, só fica menos esperto"). A resposta do endpoint inclui `provider: "typesafe" | "similarity"` para transparência.
- **Separação pura/adaptador mantida**: `app/modules/kits/matching.py` ganhou `build_role_candidates`/`suggest_kit_fields_by_role`/`unclustered_candidates`/`candidates_to_members`/`merge_suggestion_lists`, funções **puras** (sem HTTP) que só recebem a resposta já classificada e agrupam/combinam — testáveis sem mockar rede (`test_kit_matching.py`). A chamada HTTP em si (retry com backoff em 429/5xx, sem retry em 401, timeout) vive só em `app/adapters/ai/typesafe.py` (`TypeSafeRoleClassifier`), testada à parte com `httpx.MockTransport` (`test_kit_role_classifier.py`) e verificada de verdade contra a API real da TypeSafe antes de fechar a feature — foi essa verificação real, não os mocks, que pegou o bug do item anterior.
- **Privacidade**: só rótulo, tipo do campo e nome do gerador são enviados a cada classificação — nunca um valor preenchido pelo usuário (que neste ponto do fluxo, antes de qualquer geração, nem existe). Coberto por teste (`test_classifier_request_only_carries_label_type_and_generator_name`).
- **Escopo desta versão**: só o auto-detect de kits. A sugestão de campos no upload de um documento novo (D10) continua só com regras + `AnthropicMessagesProvider`/heurística local — estender a classificação semântica para lá é um próximo passo natural, não incluído aqui.

## D26 — Novas regras determinísticas (ano, mês, numeração de duplicatas, papel antes de um nome) e opção nova no lote
- **Pedido do usuário**: quatro melhorias pontuais na detecção de campos do upload (D10) — (1) dois campos iguais no mesmo documento (ex.: dois CNPJs) virarem "CNPJ 1"/"CNPJ 2" em vez de dois cartões idênticos; (2) uma palavra solta de mês (ex.: "outubro") virar um campo "Mês", **lista suspensa** com os 12 meses, não só texto; (3) um nome de pessoa logo depois de uma palavra de papel (ex.: "CONTRATANTE") ganhar o rótulo do papel ("Contratante") em vez de "Nome" genérico — e o mesmo esquema de numeração do item 1 se dois nomes diferentes tiverem o mesmo papel; (4) um número de 4 dígitos 19xx/20xx isolado virar um campo "Ano". Além disso, na importação de planilha para lote: se uma célula tiver um valor que não existe ainda na lista suspensa do campo, perguntar se quer adicionar (mostrando as opções atuais), em vez de só marcar erro.
- **Ano e mês são regras novas em `rules.py`** (mesmo motor de D10, não um provedor de IA): `\b(19|20)\d{2}\b` (tipo `number`) e o `_MONTH_RE` que já existia para datas por extenso, agora numa regra própria (tipo `select`, com `config={"options": MONTH_OPTIONS}` — os 12 meses prontos, não só o mês encontrado no texto). **Sobreposição com as regras de data é proposital e resolvida pela confiança**: um "2026" dentro de "01/10/2026" ou "21 de outubro de 2026" é capturado pelas DUAS regras novas E pela regra de data no mesmo trecho; `resolve_overlaps` (que já existia) mantém só a de maior confiança — ano/mês (0,72/0,6) perdem para data (0,9/0,92) quando se sobrepõem, e sobrevivem sozinhos quando aparecem soltos no texto (verificado contra um documento real com os dois casos).
- **Papel antes de um nome**: o motor de D10 já tinha essa lógica (`_role_before`/`_with_role` em `rules.py`) para CPF/CNPJ/etc., mas só o provedor LOCAL (`app/adapters/ai/local.py`) detecta NOMES DE PESSOA (via `_NAME_RE` + contagem de repetição ≥2), e não a usava. Em vez de duplicar a lista de papéis, `ROLE_WORDS`/`role_before` foram movidos para `app/modules/fields/types.py` (módulo já compartilhado por ambos) e `local.py` passou a chamá-la: para cada nome repetido, olha o papel na **primeira ocorrência** e aplica o MESMO papel a todas as ocorrências seguintes (mesmo que uma menção posterior não tenha o rótulo por perto) — isso evita que o mesmo valor vire dois campos (um "Contratante", outro "Nome") só por causa de onde a palavra de papel apareceu.
- **Numeração de duplicatas**: `_number_duplicate_hits` (novo, em `suggestions/service.py::materialize`) — depois que `resolve_overlaps` decide quais trechos sobrevivem, agrupa por (nome técnico, texto) pra achar VALORES distintos; se mais de um valor distinto compartilha o mesmo nome-base (ex.: dois CNPJs diferentes), numera nome e rótulo em ordem de aparição no documento ("CNPJ 1", "CNPJ 2"…); ocorrências repetidas do MESMO valor continuam um campo só (não numeradas — é o valor que distingue, não a posição). Roda **depois** do filtro de sugestões ignoradas/já cobertas, pra numerar só o que o usuário realmente vai ver.
- **Achado real ao rodar a suíte E2E**: o documento de demonstração tem DUAS datas de verdade ("01/10/2026" no corpo e "21 de setembro de 2026" na assinatura) — antes, "aceitar todas" as duas criava dois campos que só se distinguiam depois, no `accept()`, por `unique_name` (`data` e `data_2`, meio arbitrário). Com a numeração nova, as DUAS já chegam distintas na tela de sugestões como "Data 1"/"Data 2" — o comportamento mudou de propósito (é o que D26 pede), então o teste E2E (`individual.spec.ts`) foi atualizado para os nomes novos, não revertido.
- **Opções pré-definidas numa sugestão `select`**: até aqui, aceitar uma sugestão `select` sempre criava a lista de opções com só UM item — o texto encontrado (`app/modules/suggestions/service.py::accept`, comportamento de antes do D26, ainda vale para `tipo_servico`). O mês precisa dos 12 de uma vez. Em vez de um campo novo no banco, a lista pronta viaja dentro de `Hit.config`/`FieldSuggestion.suggested_config` (`{"options": [...]}"`, já existente para `decimals`/`date_format`) — e `accept()` extrai `"options"` de lá quando presente (usando-a no lugar do texto único) e **remove** essa chave antes de gravar o `config` do campo (não é um parâmetro de tipo, é só metadado da sugestão). Coberto por teste de integração (aceitar a sugestão de mês cria os 12 meses, não só o mês do texto).
- **Lote: opção nova vinda da planilha**. A validação de `select` já existia (`normalize_value`, `fields/normalize.py`) e já recusava valor fora da lista com a mesma mensagem de sempre — isso não mudou. O que mudou é só o FRONTEND: depois de `POST .../batch/imports/{id}/apply`, o diálogo de importação (`import-dialog.tsx`) cruza as linhas com esse erro específico contra as opções atuais de cada campo `select` mapeado (agora devolvidas por `POST /generators/{id}/batch/imports`, que passou a incluir `id`/`options` de cada campo) e, se achar valor novo, mostra um passo extra — opções atuais + checkboxes dos valores novos — antes de entrar na grade. Confirmando, chama `PUT /fields/{id}/options` (substitui a lista inteira — não existe endpoint de "acrescentar uma opção", então o cliente lê o que já tem e reenvia com o novo no fim) e reroda `POST .../batch/validate` com as mesmas linhas.
- **Bug real pego só testando no navegador de verdade**: depois de adicionar a opção no servidor, a grade **continuava** acusando erro na célula — a validação da grade roda no CLIENTE, com os campos já carregados na página (`useQuery(["form", id])`, sem saber que o servidor mudou). Corrigido invalidando essa query (`queryClient.invalidateQueries({queryKey: ["form", generatorId]})`) antes de reler a validação — sem isso, o usuário via "adicionado com sucesso" e a célula continuava vermelha. Coberto por um teste E2E que dirige um upload de arquivo de verdade (`setInputFiles`, sem mocks) e confere que a linha fica válida depois de clicar "Adicionar".
- **`RULES_VERSION` foi de `r1` para `r2`**: novas regras mudam o resultado de uma análise já em cache (`ai_analysis_runs`, chave inclui `prompt_version = f"{PROMPT_VERSION}-{RULES_VERSION}"`, ver D10) — sem o bump, geradores já analisados antes deste release continuariam reaproveitando o resultado antigo até uma reanálise forçada.

## D27 — Revisão de UX: fluxo em etapas (Modelo → Campos → Revisão → Gerar)
- **Problema**: não ficava claro em que ponto se estava nem qual era o próximo passo. O editor tinha 6 abas (Campos/Estrutura/Buscar + Campo/Sugestões/Documento), com a lista de campos longe da configuração. "Gerador" e "modelo" eram usados para a mesma coisa. Algumas ações pareciam funcionar sem concluir a tarefa: "Continuar configurando" num gerador sem .docx levava a um erro sem saída; "Aceitar" em sugestões de trechos que já eram campo terminava em 409; "Preencher" com 0 campos gerava uma cópia do original.
- **Decisão**:
  - Cada gerador tem **4 etapas navegáveis** (`GeneratorSteps`, `aria-current="step"`, etapas bloqueadas com o motivo). Rotas: `/generators/[id]/template` (nova: enviar ou trocar o .docx, versões), `/edit` (Campos), `/review` (nova) e `/use` + `/batch` (Gerar, com abas "Um documento | Vários documentos").
  - O painel manda cada gerador para a próxima etapa que falta (`nextHref`).
  - **Termos**: *gerador* é a coisa reutilizável; *modelo* é o documento .docx. Os tipos passam a se chamar "Lista de opções" e "Caixa de marcar", e os nomes técnicos viram "código do campo".
- **Pendências calculadas no cliente** (`lib/fields/issues.ts`, com testes unitários):
  - Nome repetido (comparado sem acento nem maiúsculas) e campo fora do documento geram *aviso*.
  - Lista sem opções e campo sem nome geram *erro*.
  - Não bloqueiam a geração, porque o servidor também não bloqueia: aparecem no editor (lista, chip e formulário do campo) e na revisão, com link "Corrigir no editor" (`/edit?field=<id>`).
- **Ordem do formulário = ordem do documento** enquanto a pessoa não reordenar manualmente. Criar, reaproveitar ou aceitar campos reordena pela primeira aparição (cabeçalho → corpo → rodapé) e grava com `PUT /fields/order`. Reordenar à mão desliga a sincronização; o botão "Seguir a ordem do documento" religa. Nada novo no banco: na abertura, a lista está "na ordem do documento" se `position` coincidir com ela.
- **Configuração do campo**: o salvamento automático (700 ms) agora também salva o que ficou pendente ao trocar de campo ou de tela antes do prazo, avisa ao fechar a aba e informa o estado ao indicador do topo ("Salvando…/Tudo salvo/Campo não salvo").
- **Dados de exemplo** (`lib/fields/samples.ts`): exemplo configurado → valor já preenchido → trecho original do documento → valor genérico válido por tipo. Todo candidato passa pela mesma validação do formulário, então um CPF de exemplo inválido nunca aparece. São usados na prévia da revisão, no botão "Preencher com dados de exemplo" do formulário e na "linha de exemplo" da planilha.
- **Rascunho do formulário individual**: automático, no `localStorage` (como já era o do lote); antes era só manual. Os dados preenchidos não vão ao servidor antes de gerar (mesma política de antes). "Limpar" pede confirmação.
- **Backend (mudanças pequenas)**:
  - `GET /generators/{id}/suggestions` (pendentes) passou a omitir sugestões que não podem mais ser aceitas (trecho apagado ou já transformado em campo à mão), usando a mesma verificação do aceite (`_locate` + `replace_range_with_field`). Isso corrigiu `test_stale_suggestion_disappears_and_never_creates_an_empty_field`, que falhava.
  - `version.source_filename` foi incluído no editor e em `/versions`, para a etapa Modelo mostrar o arquivo em uso.
- **Acessibilidade**:
  - `ButtonLink`/`ButtonAnchor` substituem `<Link><Button/></Link>` e `<a><button/></a>`, que davam duas paradas de Tab para uma ação.
  - Menu principal só com ícones no celular (texto para leitor de tela).
  - Contêineres roláveis com `relative`: sem isso, o `<caption class="sr-only">` das tabelas alargava a página no celular.
  - Foco visível nos seletores com checkbox escondido e soltar arquivo na importação (antes o navegador abria o arquivo).
- **E2E**: a suíte estava desatualizada em relação à interface. Foi reescrita para o fluxo atual, com casos novos: gerador sem documento, pendências e salvamento no editor, planilha vazia e linha de exemplo, e axe em todas as etapas.

## D28 — Fase 0: PDF digitado, "modelo", colar tabela e o que nunca sai para fora
- **PDF digitado vira .docx**: o resto do sistema continua trabalhando só com .docx. `docx_engine/pdf_import.py` converte (pdfplumber + python-docx; licenças MIT/BSD/Apache — PyMuPDF e pdf2docx ficaram de fora por serem AGPL). Roda em **processo filho** com tempo (60 s), memória (2 GB, Linux) e páginas (40) limitados.
- **Digitado × digitalizado**: página com texto visível suficiente é digitada (mesmo com papel timbrado); sem letras visíveis e com muita área de imagem é digitalizada. A camada de OCR de scanners usa texto *invisível* (modo de renderização 3) e por isso **não conta**. Digitalizado é recusado (`PDF_SCANNED`) de propósito: OCR erra justamente nomes, CPFs e valores, que viram campos. Texto desenhado ou sem mapeamento Unicode → `PDF_TEXT_UNREADABLE`.
- **Nomes**: "modelo" é a coisa reutilizável e a 1ª etapa é "Documento" (Documento → Campos → Revisão → Gerar). O código `{gerador}` dos nomes de arquivo continua valendo; `{modelo}` é o novo padrão e um campo chamado "modelo" vence o nome.
- **Cole aqui**: `POST /batch/identify` escolhe o modelo pela tabela colada (nome do título, grafia parecida, conteúdo; semântico opcional). A tela leva as linhas ao lote pelo `sessionStorage`.
- **Segurança (classificador externo)**: o classificador semântico recebe só rótulos de colunas e de campos. Se a 1ª linha colada parece **dado** (CPF, CNPJ, e-mail, data, CEP, valor, número, telefone), ela não é tratada como título: entra como amostra, só o casamento local roda e nada vai ao serviço externo (`header_looks_like_data`). Teste com espião no classificador em `test_identify.py`.
- **Correção**: a data "01/02/2027" tem 8 dígitos e era lida como CEP no casamento por conteúdo; agora a data é testada antes.

## D29 — Hipótese de entrada comercial e restrição de gastos
- **Pedido**: continuar todas as fases, tomando decisões e deixando para depois tudo que gere custo.
- **Decisão de trabalho**: priorizar escritórios pequenos de advocacia (1–5 pessoas) que já usam documentos próprios em Word; começar com self-service para automatizar preenchimento e geração em lote/kit, sem prometer aconselhamento jurídico. Minuta continua nome de trabalho.
- **Preço para pesquisa, não para cobrança**: testar R$ 49,90/mês individual e R$ 99,90/mês equipe; documentos por mês como eixo principal e limites de modelos/usuários como secundários. São valores hipotéticos, ancorados em páginas públicas de alternativas consultadas em 15/10/2026. Não publicar nem cobrar.
- **Validação**: buscar 8–12 escritórios para entrevistas/testes; meta direcional do piloto: 60% dos participantes ativados em até 5 min e 40% dos ativados retornando em D7, sem incidente crítico.
- **Gastos e atos externos**: adiar domínio, registro de marca, contratação de hospedagem/gateway/e-mail, pesquisa paga, jurídico, anúncios, cobrança e publicação. Trabalho local e uso de infraestrutura já disponível continuam permitidos; sem apagar dados ou enviar conteúdo documental a terceiros.
- **Consequências**: estratégia e design podem avançar sem custo. Preço, demanda, nome e viabilidade de piloto seguem hipóteses até validação; o lançamento continua bloqueado pelos gates de segurança/LGPD, pareceres profissionais, custos e aprovação final do Daniel.
- **Registro detalhado**: [ESTRATEGIA_COMERCIAL.md](ESTRATEGIA_COMERCIAL.md).

## D30 — Travas do piloto pós-revisão de segurança (PDF, IA externa, eliminação, retenção)
- **PDF como modelo desligado** (`PDF_IMPORT_ENABLED=false` por padrão no código e no compose). Motivo: a conversão (pdfplumber/pypdfium2) roda em processo filho, mas sem isolamento real de rede ou sistema de arquivos, e os limites de recurso só valem no Linux. Religar exige um sandbox dedicado (feito em D35). Recusa: `PDF_IMPORT_DISABLED`; a interface lê `features.pdf_import` em `/auth/me` e só oferece Word.
- **IA externa desligada** (`EXTERNAL_AI_ENABLED=false`): `get_ai_provider` devolve só o provedor local e `get_role_classifier` devolve `None`, mesmo com chaves configuradas. `AI_PROVIDER=none` continua significando "só regras".
- **`purge-workspace` em duas fases** (`app/modules/privacy.py`): primeiro marca `deleted_at` (acesso bloqueado), depois apaga o storage, e só sem falhas apaga o banco, com DELETE direto e cascata das FKs. O código anterior apagava os registros mesmo quando o storage falhava (arquivos órfãos sem chave para achá-los) e, pelo ORM, nem conseguia apagar um workspace com membros (tentava anular `workspace_members.workspace_id`).
- **Cleanup monitorado**: saída ≠ 0 em falha e evento `cleanup_concluido` com contadores.
- **Retenção/exportação documentadas com precisão** em [RETENCAO_E_ELIMINACAO.md](RETENCAO_E_ELIMINACAO.md), inclusive o que ainda não expira (`template_files`, `generation_items.values`), logs e backups (fora do repositório).
- Sem nova arquitetura: só configuração, uma função e documentação. Testes: `test_pilot_safety.py` e `test_privacy_cli.py`; o E2E `pdf.spec.ts` cobre os dois modos.

## D31 — Tipo de campo OAB com migration própria (0005)
- **Decisão (Product Owner, opção A)**: o tipo `oab` entra no vocabulário de tipos (`fields` e `kit_fields`), em vez de virar uma máscara de texto curto, para ter validação, formatação, sugestão automática e coluna própria na planilha-modelo.
- **Canônico** "UF NÚMERO[-SUFIXO]" (ex.: "ES 12345", "SP 123456-A"); **no documento** "OAB/ES 12.345". Aceita "OAB/ES 12.345", "ES 12345", "12.345/ES", "OAB-SP nº 123.456-A"; sufixos A (suplementar), B (transferência), E (estagiário); recusa UF inexistente, zero e mais de 6 dígitos. Mesma regra no servidor e no cliente (vetores compartilhados).
- **Sugestão**: "OAB/UF [nº] número" vira campo OAB (com o papel da parte, ex.: `oab_outorgado`). "inscrita na OAB/SP sob o nº …" fica de fora, porque substituir o trecho mudaria a redação.
- **Migration 0005**: troca a restrição CHECK das duas tabelas. O downgrade converte campos `oab` em `text_short` antes de recriar a restrição antiga, então não falha com dados existentes. Testada em PostgreSQL 17 (`MIGRATION_DATABASE_URL`): 0004 → head → dado `oab` → downgrade (vira `text_short`) → head → `alembic check`. Aplicada na stack `minuta-fase0` pelo serviço `migrate`.

## D32 — Métricas de ativação só agregadas e opt-in (item 9a)
- **Pedido (revisão de segurança + Product Owner)**: medir a meta do piloto (1º documento em até 5 min, retorno em D7) sem eventos individuais, sem IDs pseudônimos, sem horário exato, sem IP/UUID/PII/conteúdo/atributo livre, sem detalhamento por cliente, sem reaproveitar `audit_events` nem `/metrics`; agregados sem FK e retenção máxima de 30 dias com limpeza monitorada.
- **Decisão**:
  - Nada de coleta de eventos. Um rollup diário (`python -m app.cli metrics-rollup`) **deriva** contagens das tabelas que já existem (`workspaces`, `template_files`, `generation_jobs`); os identificadores ficam só em memória durante o cálculo.
  - A tabela `activation_metrics` tem chave natural (tipo de período, início do período, métrica): nada de UUID de linha, workspace, usuário ou horário — só datas. Não tem FK.
  - Métricas, lista fechada com CHECK: `workspaces_novos`, `modelos_enviados`, `primeiro_documento`, `primeiro_documento_ate_5min`, `lotes_concluidos` (por dia UTC, só dias completos) e `coorte_tamanho`, `coorte_retorno_d7` (por semana de criação, só coortes cuja janela de 14 dias terminou).
  - **Supressão < 5**: o valor não é gravado (NULL + `suppressed`). O banco recusa `value < 5` (CHECK). Dias sem evento também viram linha suprimida, então 0 e 1–4 ficam indistinguíveis.
  - **Opt-in** (`ACTIVATION_METRICS_ENABLED=false` por padrão): desligado, nada é calculado nem gravado.
  - **Retenção**: rollup e `cleanup` apagam o que tiver mais de 30 dias, mesmo desligado.
  - **Leitura**: só por CLI (`metrics-report`). Não há rota de API nem visão por workspace.
- **Gate que continua aberto**: ligar no piloto exige base legal e aviso aos participantes documentados (D29/D30). Até lá, desligado.
- Migration `0006`. Testes: `test_activation_metrics.py`.

## D33 — IA via OpenRouter: um modelo por finalidade, teto de custo e "não inventa"
- **Pedido (Daniel)**: implementar recursos de IA que tirem trabalho manual, usando a chave da OpenRouter, e escolher o modelo por custo × eficácia.
- **Recursos escolhidos**, pela dor que resolvem:
  1. **Achar campos** no documento enviado. Já existia com regras; a IA sobe o recall de 53% para 92%.
  2. **Preencher com IA**: colar o e-mail, o WhatsApp ou a ficha do cliente e ver os campos preenchidos (modelo e kit).
  3. **Revisar com IA**: antes de gerar, aponta datas impossíveis, gênero trocado, extenso diferente do número e nomes divergentes. Não altera nada.
- **Modelos**, medidos com a chave real (detalhes em [IA.md](IA.md)):
  - análise: **Claude Haiku 5.5** (`OPENROUTER_MODEL`). 91,9% de recall e 94,0% de precisão no conjunto ouro, US$ 0,0009/doc. É o mesmo acerto do Sonnet 5 por 1/14 do custo.
  - preencher e revisar: **Gemini 2.5 Flash** (`OPENROUTER_ASSIST_MODEL`). 19/19 no preenchimento, 4/4 na revisão sem falso alarme, cerca de 2,7 s.
- **Garantias**:
  - o preenchimento só aceita valor com evidência no texto colado (`_grounded`);
  - todo valor passa pela validação da geração;
  - JSON estrito por schema;
  - `provider.data_collection=deny`;
  - nada de conteúdo na razão de custo.
- **Custo**:
  - reserva do pior caso antes da chamada, com `pg_advisory_xact_lock`;
  - teto por chamada (`AI_MAX_CALL_USD`) e por mês (`AI_MONTHLY_BUDGET_USD`);
  - cota por plano (`max_ai_actions_per_month`); falhas não contam.
  - Ao esgotar, a análise volta às regras locais.
- **Chave**: fica fora do repositório e do `.env`, e entra como secret do Docker (`docker-compose.ai.yml`, `OPENROUTER_KEY_FILE`). `EXTERNAL_AI_ENABLED` continua sendo a trava geral (D30).
- **Lições**:
  - Sem `temperature`: com `require_parameters`, modelos de raciocínio davam 404.
  - Modelos que raciocinam gastam tokens antes do JSON. O teto de saída tem folga, e uma resposta cortada vira `AI_TRUNCATED`.
- Migration `0007` (`ai_spend`). Testes: `test_assist_ai.py` (sem rede) e `e2e/assist-billing.spec.ts` (com a IA real, quando ligada). Avaliação reproduzível: `python -m app.cli ai-eval models`.

## D34 — Cobrança pela Stripe: cartão recorrente e Pix por período
- **Pedido (Daniel)**: usar o mesmo gateway do realoficial.com.br e deixar tudo pronto para assinar. O realoficial cobra cartão pela **Stripe** (o app deles mostra "Acessar Portal Stripe" e "Valor final na Stripe") e tem um Pix à parte, renovado à mão.
- **Decisão**:
  - **Cartão**: Checkout da Stripe em `mode=subscription` com 4 preços (Profissional e Escritório, mensal e anual). Trocar de plano, cancelar e atualizar o cartão ficam no **portal do cliente** da Stripe. O Minuta não vê nem guarda dados de cartão.
  - **Pix**: a Stripe só oferece Pix de pagamento único para contas brasileiras (Pix Automático indisponível). Por isso o Pix é cobrado **por período** (`mode=payment`, valor de `plans.json`). Ao ser pago, a assinatura `method=pix` vale até o fim do período, e um novo Pix soma ao período atual. Sem renovação automática.
  - **Webhook** `/api/v1/billing/webhook`: só confia no HMAC (`Stripe-Signature`, tolerância de 300 s, corpo até 1 MB). Cada evento é gravado em `billing_events` (id único), então reenvios não têm efeito. Eventos tratados: `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted` e `invoice.payment_failed`.
  - **Plano efetivo**: assinatura ativa vale. `past_due` tem 7 dias de tolerância. Pix vencido volta ao Grátis. Cancelada vale até o fim do período.
  - **Limites**: precedência limite manual do workspace > plano > padrão (`Ctx.limit`). Com `BILLING_ENABLED=false` (padrão), nada muda para quem já usa: valem os limites padrão.
  - **Planos**: uma fonte por lado (`frontend/src/content/plans.json` para a landing e a tela; `backend/app/modules/billing/plans.json` para os limites). Um teste confere que os dois são iguais.
- **Sem SDK da Stripe**: chamadas HTTP diretas (form-encoded) em `stripe_client.py`, com a verificação HMAC implementada e testada. É menos uma dependência.
- **Tela**: `/assinatura` ("Plano e uso", no menu do usuário). Mostra o plano, os medidores do mês (documentos, modelos, usos de IA), a escolha mensal ou anual, cartão e Pix, e o portal. A landing manda `?plano=&ciclo=` para o cadastro, que segue para essa tela com o plano destacado.
- **Pendente (Daniel)**: abrir a conta e configurar produtos, webhook e portal, seguindo o passo a passo em [PAGAMENTOS.md](PAGAMENTOS.md). Migration `0008`. Testes: `test_billing.py` e `e2e/assist-billing.spec.ts`.

## D35 — Conversão de PDF isolada em contêiner próprio (religa o PDF como modelo)
- **Pedido (Daniel)**: "isole a conversão de PDF". A landing promete Word ou PDF, e o PDF estava desligado desde D30 por falta de isolamento real.
- **Decisão**: o leitor de PDF (PDFium/pdfminer, a parte mais exposta a arquivo malicioso) sai da API e vai para o serviço `pdfconv` (`app/pdfconv/server.py`, alvo `pdfconv` do Dockerfile). É um servidor HTTP mínimo da biblioteca padrão: `GET /health` e `POST /convert`, com o PDF no corpo e o `.docx` em base64 na resposta. Isolamento no `docker-compose.yml`:
  - **sem segredos**: o serviço não recebe `x-app-env` (nada de banco, storage, Redis, chaves);
  - **rede**: só `pdfnet` (`internal: true`), sem saída para a internet e sem porta no host. Só a API (`networks: [default, pdfnet]`) o alcança;
  - **contêiner**: `read_only` + `/tmp` tmpfs de 64 MB, uid 10001, `cap_drop: ALL`, `no-new-privileges`, `mem_limit: 1g`, `cpus: 1`, `pids_limit: 64`;
  - **por arquivo**: processo filho descartável com timeout e `RLIMIT_AS`/`RLIMIT_CPU` (`PDFCONV_MEMORY_MB`), no máximo 4 conversões simultâneas (503 acima disso), limite próprio de tamanho (16 MB) e de páginas (40);
  - **saída não confiável**: a API valida o `.docx` convertido com `validate_docx`, como qualquer upload. Antes, o `.docx` convertido entrava sem essa checagem.
- **Modo** (`Settings.pdf_import_mode`):
  - `service` com `PDF_CONVERTER_URL`;
  - `process` (processo filho local) só fora de produção;
  - `off` em produção sem conversor isolado, mesmo com `PDF_IMPORT_ENABLED=true`.
  - O compose liga o PDF (`PDF_IMPORT_ENABLED=true`, `PDF_CONVERTER_URL=http://pdfconv:8090`); o padrão do código continua `false`.
- **Verificado de dentro do contêiner** (stack `minuta-fase0`, 22/10/2026):
  - uid 10001, `CapEff=0`, `NoNewPrivs=1`;
  - gravar em `/app` e `/home` falha; só `/tmp` aceita escrita;
  - nenhuma variável sensível e sem `/run/secrets`;
  - `postgres`, `redis`, `minio`, `openrouter.ai` e `google.com` não resolvem; TCP para 1.1.1.1:443 e 8.8.8.8:53 falha;
  - cgroup com `memory.max=1 GiB`, `pids.max=64` e 1 CPU;
  - nenhuma porta publicada.
  - Ponta a ponta pela API: PDF digitado aceito (2,2 s), digitalizado recusado com `PDF_SCANNED`.
  - O conversor ainda resolve a própria API na rede interna. É o mesmo acesso público que ela já tem: sem sessão, nada é liberado.
- **Limites conhecidos**: sem gVisor/seccomp customizado (fica o perfil padrão do Docker). Para um host multi-inquilino, considerar `runtime: runsc`.
- Testes: `test_pdfconv.py` (serviço e cliente por HTTP real, recusas com código, limite de tamanho, 503, serviço fora do ar, modo em produção, upload pelo serviço e validação da saída). Seguem valendo `test_pdf_import.py` e `test_pilot_safety.py`.
- **Fidelidade (1º teste com PDF real de usuário, 22/10/2026)**: uma declaração exportada do Word saiu como tabela de 6 linhas com bordas, sem centralização, sem a linha de assinatura e em fonte com serifa. Causas e correções:
  - o Word desenha um **retângulo branco sem borda** atrás de cada linha de parágrafo com fundo, e o detector de tabelas o contava como borda → as tabelas agora só usam bordas visíveis (`_visible`);
  - **traço solto** (linha de assinatura, separador) era descartado → vira parágrafo vazio de 1 pt com borda inferior, na mesma posição e largura (`RuleItem`). Sublinhado de texto continua sublinhado;
  - **fonte ausente no worker** (Consolas) caía em DejaVu Serif no PDF → `/etc/fonts/local.conf` com substitutas do mesmo tipo e vínculo forte (Consolas → Liberation Mono, Segoe UI → Liberation Sans, Georgia → Liberation Serif…). Com o vínculo fraco, o LibreOffice ignorava o apelido;
  - **data por extenso** sugerida pela IA perdia o formato e saía "15/03/2027" → a sugestão escolhida herda a configuração da regra no mesmo trecho, e datas por extenso da IA nascem `date_format: long`.
  - Teste com PDF fictício de mesma estrutura: `test_paragraph_background_is_not_a_table_and_signature_line_survives`. Antes da correção ele gerava 1 tabela.

## D36 — Rebranding: Minuta vira DocFeito
- **Pedido (Daniel)**: minuta.com.br não estava disponível. Ele escolheu **DocFeito** (docfeito.com.br livre) e pediu o rebranding inteiro: logo, identidade visual em PDF, landing e interface. Sem aprovação criativa; só de custo (US$ 5 aprovados para imagens).
- **Processo**:
  - 6 estudos de símbolo no Recraft v4.1 Vector (US$ 0,48 no total; US$ 0,08 cada, em SVG).
  - Escolhido o conceito "folha com o canto que vira check". Refinado à mão em geometria de 64 unidades: dobra verde e check subindo para a dobra, com máscara para funcionar sobre qualquer fundo.
  - Comparado com a variante "check atravessando a folha", que lembrava um ícone genérico de checkbox.
  - Kit gerado em código (`scripts/brand_build.py`, nome em contornos da Plus Jakarta), PNGs transparentes renderizados do vetor, sem "tirar fundo", e manual em PDF de 11 páginas (`scripts/brand_book.cjs`).
- **Identidade**:
  - Cores: tinta `#0E1A2B`, verde `#12B886` e verde de ação `#0B7A5A` (AA com branco).
  - Marca-texto amarelo `#FFD43B`: é o gesto de destacar o que muda no documento. Vira a assinatura visual e a cor das chamadas principais.
  - Fundo papel quente. Tipografia Plus Jakarta Sans + Inter.
- **Produto**:
  - Tokens de tema trocados (claro e escuro). Chips de campo do editor em verde ("feito"); a sugestão a conferir continua amarela.
  - Landing com o título "Documento feito. Sem copiar e colar.", botões em marca-texto e campos destacados em amarelo.
  - Login e cadastro, favicon, ícone de app e imagem de compartilhamento novos.
  - Cenas da landing recompostas com o app novo e vídeo regravado do app real.
- **Nome**:
  - "DocFeito" em tudo o que o usuário vê: site, app, termos, privacidade, nome da API, produtos na Stripe, título da tela de pagamento e do portal, X-Title da OpenRouter.
  - Contas demo `@docfeito.com.br`, com limites de demonstração no seed para não caírem no plano Grátis quando a cobrança está ligada.
- **Mantido de propósito**:
  - Identificadores técnicos invisíveis: cookie `minuta_csrf`, chaves `minuta:` do navegador, projeto e banco `minuta` do Docker, `~/.minuta`, pacote `minuta_backend`, metadata `minuta_plan` na Stripe. Renomear deslogaria todo mundo e apagaria rascunhos.
  - O histórico destas decisões (D01–D35) continua dizendo "Minuta".
- Detalhes e arquivos: [MARCA.md](MARCA.md).

## D37 — Preencher com a foto dos documentos do cliente (RG, CNH, comprovante)
- **Pedido (Daniel)**: nova feature com IA. A dor escolhida: o cliente manda pelo WhatsApp a foto do RG/CNH e da conta de luz, e alguém digita nome, CPF, RG, endereço e CEP no formulário.
- **Decisão**: o "Preencher com IA" ganha a aba **Foto ou PDF**, ao lado de "Colar texto". O usuário arrasta, escolhe ou cola (Ctrl+V) até 4 arquivos (JPG, PNG, WEBP ou PDF, 8 MB cada). Uma chamada ao Gemini 2.5 Flash (o mesmo modelo de preencher e revisar) lê todos os arquivos juntos e devolve valor + evidência ("CNH, campo nome") para cada campo. Rotas: `POST /generators/{id}/assist/fill-files` e `POST /kits/{id}/assist/fill-files` (multipart `files`).
- **Garantias**:
  - **foto regravada antes de sair**: aberta, girada conforme a câmera, reduzida a 2.000 px e salva de novo em JPEG — sem metadados (aparelho, GPS) e com menos tokens. Imagem acima de 50 Mpx é recusada;
  - **PDF não é aberto na API** (o leitor de PDF só roda isolado, D35): vai como arquivo para a IA ler; o nome original do arquivo não é enviado (`documento-N.pdf`);
  - **não inventa**: valor sem evidência é descartado; campo que não é dado de documento (valor do contrato, prazo) fica vazio; todo valor passa pela validação do tipo (CPF com dígito ilegível vai marcado em vermelho);
  - nada é gravado: a auditoria guarda só quantidade/tipo de arquivo e contagens; mesma cota e tetos de custo da IA (D33), `data_collection: deny`.
- **Medido** (documentos fictícios: conta de luz de empresa inventada + ficha cadastral, fotografadas tortas, com ruído e compressão de WhatsApp): 8 de 8 campos certos, inclusive estado civil escolhido da lista; valor do contrato e data de início corretamente vazios; 4,5 s; US$ 0,0012 por leitura.
- Testes: `test_assist_ai.py` (foto sem metadados e reduzida, PDF sem nome original, valor sem evidência descartado, tipo inválido/arquivos demais/imagem quebrada recusados sem chamar a IA, trava geral) e `e2e/assist-photo.spec.ts` (com a IA real, quando ligada; imagens fictícias em `e2e/fixtures/*_ficticia.jpg`).

## D38 — Teste grátis na landing, sem cadastro (e o IP real do cliente)
- **Pedido (Daniel, sprint)**: o visitante envia o documento DELE na landing, vê a IA marcar os campos e cria a conta para guardar o modelo. É o que mais converte. Especificação: `docs/specs/SPRINT_TESTE_LINK_ASSINATURA.md`; requisitos da segurança: `docs/SEGURANCA_SPRINT.md` (OBR-0 a OBR-8).
- **Pré-requisito — IP real do cliente** (`app/core/net.py`, função única `client_ip`):
  - o rewrite de `/api/*` do Next repassava o `X-Forwarded-For` do navegador como veio e não acrescentava o endereço de quem conectou; o uvicorn rodava com `--forwarded-allow-ips=*` e o `client_ip` antigo pegava o 1º item. Resultado (prova de conceito da segurança): 12 cadastros com limite de 10/h, trocando o cabeçalho;
  - agora o Next acrescenta o IP do socket ao cabeçalho (`src/instrumentation.ts` → `lib/server/forwarded-for.ts`, no estilo `$proxy_add_x_forwarded_for` do nginx), o uvicorn roda com `--no-proxy-headers`, e a API só aceita o cabeçalho vindo de `TRUSTED_PROXIES` (padrão: loopback, 10/8 e 172.16/12), lendo da direita para a esquerda no máximo `TRUSTED_PROXY_HOPS` saltos (1 = só o Next). O que o cliente escreve fica à esquerda e nunca é lido;
  - por que o limite de saltos: no desenvolvimento o navegador está em 127.0.0.1 e, no compose, chega ao Next pelo gateway do Docker (172.x.0.1) — endereços de proxy confiável. Sem o limite, a varredura passaria por eles e aceitaria o cabeçalho do cliente;
  - o compose publica a API só em 127.0.0.1 (quem chega direto pela porta publicada aparece com o IP do gateway, que é confiável). Em produção, a API não deve ter porta pública.
- **Fluxo**: bloco "Teste com o seu documento" na seção de demonstração (`components/site/trial-upload.tsx`) → `POST /api/v1/public/trials` (multipart) → o worker converte/lê/analisa (fila própria `trial`) → a página consulta `GET /public/trials/{token}` → prévia com os campos em marca-texto (mesmo JSON do editor, `DocPreview` no modo `found`) e a lista de campos → `/register?trial=<token>` ou `/login?trial=<token>` → `POST /trials/{token}/claim` cria o modelo com o documento e as sugestões e leva à etapa Campos.
- **Controles de custo e abuso** (a entrada é anônima e tratada como hostil):
  - trava `TRIAL_ENABLED` (sem valor: ligado fora de produção, desligado em produção);
  - limites por IP real e por rede, contando **tentativas** (OBR-1: recusa, arquivo quebrado e falha da IA também gastam a vez): 3/h e 10/dia por IP, 30/dia por /24 (IPv4) ou /64 (IPv6). As chaves do limitador são HMAC do IP (nada de IP em claro no Redis nem no banco);
  - no máximo `TRIAL_MAX_CONCURRENT` (3) testes na fila ou em processamento no sistema todo, contados sob trava (`pg_advisory_xact_lock`); acima disso, 429 `TRIAL_BUSY` ("tente em instantes"). Teste parado há 5 min não ocupa vaga e a limpeza o encerra;
  - Cloudflare Turnstile quando `TURNSTILE_SECRET_KEY` está configurada (validação no servidor, falha fechada, `action=trial`); sem a chave, valem os limites. Campo-armadilha `website`: preenchido, responde como sucesso e não guarda nada;
  - arquivo: tamanho conferido pelo `Content-Length` ANTES de ler o corpo (413), até 5 MB; `.docx` pelo `validate_docx` com limites menores que os das contas (300 partes, 15 MB por parte, **25 MB descompactados** — um .docx de 1 MB que vira 78 MB custava 6,7 s e 523 MB de RAM no parse); PDF só pelo conversor isolado (D35) com até 10 páginas; `.docx` com mais de 10 páginas (contagem do Word ou ~4.000 caracteres por página) é recusado. Nada de gerar DOCX/PDF: só a análise;
  - **IA com orçamento próprio** (OBR-3/OBR-5): finalidade `trial` no `ai_budget`, reservada antes da chamada contra `TRIAL_AI_DAILY_BUDGET_USD` (0,50/dia) e **fora** do `AI_MONTHLY_BUDGET_USD` dos clientes (que passou a excluir `trial`): um atacante não consegue derrubar a IA de quem paga. Esgotou ou caiu → só regras e heurísticas locais, sem custo, com aviso discreto ("budget"). A IA lê só os primeiros 6.000 caracteres; o resto do documento passa pelas heurísticas locais. Provedor externo sem teto por finalidade (Anthropic direto) nunca é usado para anônimo.
- **Privacidade**: token de 32 bytes aleatórios, guardado só como SHA-256; 404 igual para token errado, vencido ou já guardado. Arquivo e resultado somem no `claim` ou em 1 hora (limpeza no watchdog a cada 5 min e no `python -m app.cli cleanup`). Log só com formato, tamanho, códigos e contagens. A landing e `/r/…` têm CSP com nonce por requisição (`src/proxy.ts`, sem `unsafe-inline` em script; a landing passou a ser renderizada por requisição) e o documento é sempre texto escapado pelo React.
- **Claim**: reaproveita o `.docx` já validado (o PDF já foi trocado pelo convertido) e cria a versão com `create_version(..., analyze=False)`; as sugestões vêm dos achados do teste (`materialize`), com uma `ai_analysis_runs` de `prompt_version` próprio (`…-trial`) para "Analisar de novo" ler o documento inteiro em vez de reaproveitar. Nada de nova análise nem de custo na conta. Limite do plano estourado: o teste volta a ficar disponível para tentar de novo.
- **Pior caso de custo**: 0,50 US$/dia de IA no teste (≈ 15 US$/mês), independente do volume de ataque; fora isso, só CPU de parse limitada por 3 simultâneos.
- Migration `0009` (tabela `trials` e finalidade `trial` no CHECK de `ai_spend`). Testes: `test_trials.py`, `test_client_ip.py`, `test_trial_security.py` (da segurança) e `e2e/trial.spec.ts`.
- **Depois da revisão (segurança F2-1..F2-5 e QA-1/QA-2)**: o log de acesso mascara o token no caminho (`/public/trials/`, `/trials/`, `/public/requests/`, `/signatures/webhook/…/`); com o Turnstile aprovado o limite por IP sobe para 6/h (CGNAT de celular), mantendo /24 e orçamento; com as vagas ocupadas, o envio espera até 5 s por uma vaga antes do `TRIAL_BUSY`; a resposta da armadilha tem o mesmo formato da real. QA-2: `resolve_overlaps` comparava cada trecho com todos os escolhidos do documento (quadrático: 4 mil parágrafos levavam 4 min) — agora só com os do mesmo bloco, e as sugestões entram em lote (2 mil parágrafos: de 16 s para 6 s, linear); acima de 5.000 parágrafos a análise é parcial, com aviso. QA-1: parte comprimida corrompida (`zlib.error`/`EOFError`) virava 500; agora é recusa tipada (422) no `validate_docx`, no `parse_docx` e no teste grátis. Checklist de implantação em [SECURITY_AND_LGPD.md](SECURITY_AND_LGPD.md).
- **QA-3/QA-4 e armadilha**: um parágrafo de 38 mil caracteres com ~3.600 achados prendia o worker do teste por 112 s (a prévia chamava `replace_range_with_field` por achado, refazendo o bloco a cada vez). Agora o teste guarda no máximo 300 achados (30 por parágrafo) e monta a prévia numa passada por parágrafo (`nodes.apply_fields`, mesmo resultado do caminho um por um — teste com documentos aleatórios). Multipart malformado nas rotas públicas responde 400 tipado (`TRIAL_FORM_INVALID`/`FORM_INVALID`) em vez de 500. A armadilha grava um teste "falho" sem arquivo, que aparece "processando" por alguns segundos e depois falha com a mensagem genérica — igual a um teste real que deu errado — e conta nos mesmos limites por IP.
