# Segurança e LGPD

> Este documento descreve os controles **implementados** e o que **falta**. Não é parecer jurídico.

## Autenticação e sessão
- Senha com **Argon2id**; reprocessa hash quando os parâmetros mudam; comparação com tempo equalizado para conta inexistente.
- Sessão opaca de 256 bits em cookie **`HttpOnly`**, `SameSite=Lax`, **`Secure`** quando `COOKIE_SECURE=true` (obrigatório em `APP_ENV=production`). No banco só fica o SHA-256 do token; permite revogação e expiração deslizante.
- **CSRF**: cookie legível + cabeçalho `X-CSRF-Token` comparados com o valor guardado na sessão (não só com o cookie) em métodos inseguros, mais checagem de `Origin`.
- Rate-limit em login/cadastro/recuperação (Redis se disponível, memória caso contrário). Recuperação de senha não revela se o e-mail existe; token de 1 h, uso único; ao redefinir, as sessões são revogadas.
- Estrutura pronta para login social (`auth_identities`).

## Isolamento multi-tenant
- `workspace_id` em toda tabela de domínio e em toda consulta; IDs UUID v4; 404 para recurso alheio.
- Downloads: link assinado (HMAC) de 5 min **vinculado a usuário + workspace**; exige sessão; recusa arquivo expirado (410).
- Papéis `owner`/`member`: membro só repete/cancela gerações próprias.

## Upload e processamento de arquivos
- Extensão, magia do ZIP, estrutura OOXML e tipo de conteúdo principal; limite de tamanho por workspace.
- **ZIP bomb**: limite de razão de compressão, tamanho por entrada e total, número de entradas.
- **Macros**: `vbaProject.bin`/`macroEnabled` são recusados; nada é executado. Executáveis embutidos (`.exe`, `.dll`, `.js`…) recusados. Caminhos com `..`/absolutos recusados. Arquivos cifrados recusados.
- **XML**: DTD/entidades proibidas (XXE e *billion laughs*), sem rede. Referências externas de modelo anexado são removidas ao compilar.
- Nome interno aleatório; o nome enviado pelo usuário nunca vira caminho. O original é imutável.
- Planilhas de importação: mesma proteção de ZIP; leitura `read_only`/`data_only`; CSV de saída protegido contra injeção de fórmula.
- LibreOffice roda com perfil temporário limpo, timeout e sem rede.
- **PDF como modelo: desligado por padrão** (`PDF_IMPORT_ENABLED=false`). A conversão roda num processo filho com tempo limitado, mas os limites de memória/CPU só valem no Linux e o processo **não** fica isolado de rede nem do sistema de arquivos. Só ligar depois de um isolamento real (contêiner/sandbox dedicado, sem rede). Desligado, o servidor recusa PDF com `PDF_IMPORT_DISABLED` e a interface só oferece Word.

## Dados pessoais e logs
- **Nunca** registramos conteúdo de documentos, CPF, CNPJ, valores ou e-mails em log: o filtro de log mascara esses padrões como rede de segurança, e o código não os passa aos logs.
- **Campos estruturados do log em allowlist** (`SAFE_EXTRA_KEYS` em `core/logging.py`): IDs, contadores, método/rota/status e tipo/código de erro. Qualquer outro `extra=` é descartado; só o nome da chave aparece em `omitted_keys`. Textos permitidos passam pela máscara e são cortados em 200 caracteres. O token de download é mascarado na rota (`/downloads/[token]`).
- **Exceções** vão ao log **sem a mensagem** (só tipo, arquivo e linha, inclusive causas encadeadas): mensagens de bibliotecas podem citar trechos do documento. O erro da conversão de PDF envia ao processo pai só o tipo da exceção.
- Auditoria (`audit_events`) guarda ação, entidade, IP e contadores; chaves como `values`, `content`, `cpf`, `email` são descartadas antes de gravar.
- Mensagens de erro de itens são genéricas (não incluem valores).

## IA
- **Trava do piloto: `EXTERNAL_AI_ENABLED=false` (padrão).** Desligada, nenhum serviço externo é chamado — nem Anthropic, nem o classificador TypeSafe/Jev —, **mesmo** com `AI_PROVIDER=anthropic`/`auto` e chaves configuradas. Valem só as regras e heurísticas locais (`tests/test_pilot_safety.py`). `/auth/me` informa `features.external_ai`.
- Chamada **somente** na análise/reanálise do modelo, nunca na geração de documentos.
- **O que é enviado** ao provedor: blocos de texto do modelo (ex.: parágrafos do contrato original) e suas chaves — até `AI_MAX_CHARS` (60.000). **Não** são enviados: valores preenchidos em formulários/lotes, arquivos binários, dados de usuários.
- Recomendação: envie ao provedor apenas modelos **sem dados pessoais reais** (use nomes/CPF fictícios no modelo). Configure `AI_PROVIDER=local` ou `none` para nenhuma saída de dados.
- Resposta validada por schema; sugestões nunca alteram o modelo sem confirmação. Registramos consumo (caracteres, tokens, duração), não conteúdo. A IA não presta aconselhamento jurídico.
- Sem chave configurada, o produto usa só regras determinísticas + heurísticas locais, e a interface informa isso.

## Retenção, exportação e exclusão (LGPD)
Política completa e runbook: **[RETENCAO_E_ELIMINACAO.md](RETENCAO_E_ELIMINACAO.md)**.
- **Retenção**: arquivos gerados expiram (`FILE_RETENTION_DAYS`, padrão 7 dias). `python -m app.cli cleanup` remove do storage, sai com código ≠ 0 quando algo falha e registra `cleanup_concluido` (removidos/falhas/pendentes) para alerta. Modelos enviados (`template_files`) e valores preenchidos (`generation_items.values`) **não** expiram hoje: só saem com a eliminação do workspace.
- **Exportação** (portabilidade): `python -m app.cli export-workspace <id> saida.json [--files PASTA]` gera um JSON com **todas** as tabelas do workspace (inclusive valores preenchidos, blocos do modelo, sugestões, kits e importações) e os dados de conta dos membros, **sem** segredos (sessões, hashes de senha, tokens, chaves de idempotência). Com `--files`, copia também os arquivos do storage.
- **Eliminação**: `python -m app.cli purge-workspace <id> --yes` marca a eliminação como pendente (acesso bloqueado), apaga os arquivos do storage e **só então** apaga os registros. Se o storage falhar, sai com código 1 e mantém os registros para nova tentativa (idempotente). Na mesma transação, apaga as contas que ficaram sem nenhum workspace.
- Geradores excluídos pelo usuário sofrem *soft delete*; a exclusão definitiva ocorre via `purge-workspace`.

## Métricas de ativação (D32)
- Desligadas por padrão (`ACTIVATION_METRICS_ENABLED`). Quando ligadas, só contagens por dia ou por semana de coorte, derivadas uma vez por dia das tabelas existentes. Não há eventos, IDs, horários, IP nem conteúdo.
- Grupos com menos de 5 são suprimidos, e o banco recusa valores abaixo de 5.
- Sem FK, sem leitura por workspace, sem API. Retenção máxima de 30 dias.
- Ligar no piloto depende de base legal e aviso aos participantes.

## Transporte e repouso
- TLS deve ser terminado no proxy reverso (o compose de desenvolvimento é HTTP). Cabeçalhos de segurança básicos (`nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`) e `Cache-Control: no-store` nas respostas de API.
- Criptografia em repouso: `S3_SSE=true` habilita SSE-S3; para disco/banco use a criptografia do provedor de infraestrutura.

## O que ainda falta (honestidade)
- Convites e gestão de membros (UI), 2FA, política de senhas avançada e bloqueio progressivo por conta.
- Varredura antivírus dos uploads (ClamAV) e CSP restritiva (o Next injeta scripts inline; requer nonce).
- Consentimento/registro de operações de tratamento (RoPA), DPA com o provedor de IA, e fluxo self-service de exportação/exclusão na UI.
- Rotação de `SECRET_KEY` (invalida links assinados e reset tokens pendentes).
