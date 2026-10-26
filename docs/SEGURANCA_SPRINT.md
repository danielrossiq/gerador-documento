# Segurança da sprint — teste grátis, link do cliente, assinatura eletrônica

> Autor: agente de segurança (branch `claude/sprint-seguranca`). Companheiro de `docs/SECURITY_AND_LGPD.md` (controles
> já existentes) e da especificação `docs/specs/SPRINT_TESTE_LINK_ASSINATURA.md` (D38/D39/D40). Este documento é o
> **contrato de segurança** da sprint: modelo de ameaças, os números do pior caso de custo e os requisitos
> priorizados para o engenheiro. As provas de conceito rodaram **só contra o stack local** (API 8160, IA **falsa**
> em 127.0.0.1:8169). Nenhuma IA real foi usada: orçamento de IA real gasto nesta fase = **US$ 0**.

## 0. Resposta direta ao Daniel: o teste grátis pode virar um ataque que gera custo?

**Sim, e é a superfície mais perigosa da sprint**, porque é a única que gasta dinheiro de terceiros (OpenRouter) **sem
cadastro, sem sessão e sem ninguém por trás**. Com as travas da especificação implementadas corretamente, o risco é
pequeno e limitado. Sem elas, há dois estragos distintos: **gasto de IA** e **negação de serviço da IA para os
clientes pagantes** (a pior parte).

Premissas das contas (medidas no stack local, modelo de análise = Claude Haiku 5.5, preço de lista ~US$ 1/milhão de
tokens de entrada e ~US$ 5/milhão de saída):

- Teste lê no máximo **6.000 caracteres** (trava da spec) → ~3.300 tokens de entrada + teto de 4.000 tokens de saída.
- **Pior caso por chamada = US$ 0,0233** (é o que o `ai_budget` reserva; abaixo do `AI_MAX_CALL_USD=0,05`, então passa).
- **Custo real medido por documento curto ≈ US$ 0,0015** (a avaliação do conjunto ouro deu US$ 0,0009/doc).
- Vazão de chamadas de IA limitada pelo worker: ~8 simultâneas (2 processos × 4 threads) ≈ **4.100 chamadas/hora**;
  com worker escalado para 3, ~12.300/hora.

### Pior caso **SEM as travas específicas do teste** (só o que existe hoje)

| Janela | Custo real médio (US$ 0,0015/chamada, 8 conc.) | Pior caso por chamada (US$ 0,0233, 8 conc.) | Worker escalado ×3 (pior caso) |
|---|---:|---:|---:|
| 1 hora | US$ 6 | US$ 96 | US$ 287 |
| 1 dia (sustentado) | US$ 148 | US$ 2.299 | US$ 6.896 |
| 1 mês (botnet sustentada) | US$ 4.443 | US$ 68.960 | US$ 206.879 |

**Mas o teto global de IA que já existe (`AI_MONTHLY_BUDGET_USD=20`) é um freio real** — *se* o teste usar o mesmo
`ai_budget.reserve` (a spec exige isso). Com ele, o gasto de OpenRouter **não passa de US$ 20/mês**. O problema é que
esse teto é **compartilhado com os clientes pagantes**: o atacante **esgota os US$ 20 em ~13 minutos** (pior caso) a
~3 horas (custo real) e, a partir daí, **a análise de IA dos clientes de verdade cai para as regras locais pelo resto
do mês**. Ou seja: o gasto fica capado em US$ 20, mas vira **negação de serviço da IA** paga. Esse é o verdadeiro
dano, e é por isso que o orçamento do teste precisa ser **separado** do dos clientes (requisito OBR-5).

### Pior caso **COM as travas da spec** (budget diário do teste + por IP + /24 + concorrência + Turnstile + 6.000 chars + sem LibreOffice)

| Janela | Teto de custo de IA do teste |
|---|---:|
| 1 hora | ≤ US$ 0,50 (se o dia inteiro queimar numa hora) |
| 1 dia | ≤ US$ 0,50 (`TRIAL_AI_DAILY_BUDGET_USD`) |
| 1 mês | ≤ ~US$ 15 |

O `TRIAL_AI_DAILY_BUDGET_USD=0,50` é o **freio rígido**: mesmo um atacante com milhares de IPs não passa disso por dia,
e os limites por IP (3/h, 10/dia) e por /24 (30/dia) + Turnstile tornam caro chegar perto. Esgotado o budget do dia,
o teste continua **só com regras locais** (custo zero), com aviso discreto — exatamente como a spec pede.

**Conclusão para o Daniel:** com as travas, o pior caso é **US$ 0,50/dia (~US$ 15/mês)** e o teste nunca derruba a IA
dos clientes. Sem as travas, o gasto fica capado em US$ 20/mês pelo teto global atual, **mas** o atacante queima esse
teto em minutos e deixa os clientes pagantes sem IA até o dia 1º. Logo: **as travas OBR-1 a OBR-6 são pré-requisito
de publicação do teste grátis.** Nada de LibreOffice no teste (a spec já proíbe) elimina o vetor de CPU mais caro.

---

## 1. Modelo de ameaças

Escala: **Impacto** (B/M/A), **Probabilidade** (B/M/A) considerando o atacante típico (script contra endpoint público,
sem credencial). "Estado" = o que já protege hoje.

### 1.1 IP do cliente e limites de taxa — base de tudo

| Ameaça | I×P | Estado | Observação / PoC |
|---|---|---|---|
| **`X-Forwarded-For` forjado fura todo limite por IP** | A×A | **VULNERÁVEL hoje** | `client_ip()` (`core/deps.py`) confia cegamente no 1º item do `X-Forwarded-For`. `Dockerfile` sobe uvicorn com `--forwarded-allow-ips=*`. **PoC local confirmado**: 12 cadastros com XFF diferente a cada vez → **12×201** (o limite de 10/h simplesmente não existe); sem XFF, o 11º e 12º dão 429. 30 logins errados com 30 IPs forjados nunca travam a conta. |
| **Proxy do Next não sanitiza o XFF do cliente** | A×A | **VULNERÁVEL** | O rewrite `/api/*` do Next repassa o `X-Forwarded-For` enviado pelo navegador (o `base-server` do Next só o define se ausente; o httpxy não reescreve no rewrite). **PoC local confirmado via :3360**: cadastro com `X-Forwarded-For: 192.0.2.77` forjado passa (201) mesmo depois de a janela ter estourado sem XFF (429). |
| Atrás de um proxy que NÃO seta XFF, todos os clientes chegam com o mesmo IP | M×M | — | Aí o limite por IP viraria um limite global e bloquearia gente de verdade. |

### 1.2 Uploads (teste grátis e link do cliente)

| Ameaça | I×P | Estado |
|---|---|---|
| `.docx`/zip bomb, macro, executável, path traversal, XXE | A×B | **Coberto** por `validate_docx`/`validate_zip_container` e parse sem DTD/rede. |
| `.docx` que respeita a razão de compressão mas expande muito (memória/CPU no parse) | M×M | Parcial. **Medido local**: um `.docx` de 1,1 MB que passa no `validate_docx` expande para 78 MB → parse de **6,7 s e +523 MB** no processo. Com o limite de 5 MB do teste, o teto por `MAX_TOTAL_BYTES=250 MB` ainda permite ~20 s / ~1,5 GB. O parse roda no worker (teste) ou na API (upload normal). |
| Imagem perto de 50 Mpx (foto do documento, D37/link) | M×M | Parcial. **Medido local**: PNG de 7000×7000 (49 Mpx, abaixo do corte) decodifica em ~0,9 s e **+508 MB** por arquivo; são até 4 por requisição → ~2 GB. O `MAX_IMAGE_PIXELS=50_000_000` barra acima disso, mas 49 Mpx × 4 ainda é pesado. |
| PDF digitalizado/estranho no teste (conversão) | M×M | **Coberto** pelo serviço isolado `pdfconv` (D35): sem rede, sem segredos, 4 conversões simultâneas no máximo (503 acima), 40 páginas, 16 MB. Spec limita o teste a 5 MB/10 páginas. |

### 1.3 Custo de IA e reservas do `ai_budget`

| Ameaça | I×P | Estado |
|---|---|---|
| Teste grátis martelado gera custo de OpenRouter | A×A | Ver seção 0. Hoje capado em US$ 20/mês global, **mas sem isolamento do budget dos clientes**. |
| **Chamadas que falham queimam o teto global sem produzir resultado** | M×M | **Confirmado (PoC local)**: 50 chamadas com a IA em modo "resposta cortada" (`AI_TRUNCATED`) → **US$ 0,2654 em linhas `failed`** no `ai_spend`, e **não descontaram da cota** do workspace (`actions_used` ficou em 1). Correto para o cliente (não paga pela falha), mas um atacante que força truncagem **gasta mesmo assim**. Para o teste, o limite por IP tem de contar **tentativas**, não sucessos. |
| Reserva do pior caso bem acima do real (6–15×) | B×A | Esperado (a reserva é teto, não cobrança); mas aperta o budget diário cedo demais. Aceitável. |
| `fill-files` (foto/PDF) com PDF de muitas páginas subestima a reserva | M×M | **Medido local**: a reserva estima os tokens do PDF por bytes/páginas, mas um PDF de 1.000 páginas de 153 KB vale **~258.000 tokens reais** vs. 5.600 estimados (**46×**). O custo real (~US$ 0,077) ainda cabe no `AI_MAX_CALL_USD`, mas a reserva fica muito abaixo do real — some com os limites de página do próprio provedor. Vale apertar a estimativa. |

### 1.4 Rotas públicas e tokens (teste e link do cliente)

| Ameaça | I×P | Estado |
|---|---|---|
| Enumeração/adivinhação de token do teste (`/public/trials/{token}`) ou do link (`/r/{token}`) | A×M | A definir na implementação. **Exigir token aleatório ≥ 256 bits, guardado só como hash** (a spec já manda isso para o link; o teste deve seguir igual). 404 genérico. |
| Token do link vaza por `Referer`/histórico/log | A×M | Página pública `/r/{token}`: cuidar de `Referrer-Policy`, não pôr token em query de terceiros, mascarar no log (como `/downloads/[token]`). |
| Reuso do token do teste depois de expirar / claim repetido | M×M | Token de teste vale 1 h; `claim` autenticado só uma vez. Exigir checagem de expiração + idempotência do claim. |
| Rota pública sem sessão escapa do `check_origin`/CSRF | M×M | As rotas `/public/*` são GET/POST sem cookie; definir explicitamente que **não** herdam CSRF por sessão e aplicar anti-abuso por token+IP no lugar. |

### 1.5 Webhooks de assinatura (D40)

| Ameaça | I×P | Estado (padrão do webhook Stripe, a copiar) |
|---|---|---|
| Webhook forjado (sem assinatura do provedor) | A×M | O Stripe (`stripe_client.verify_webhook`) já faz HMAC + tolerância 300 s + corpo ≤ 1 MB. **Cada provedor de assinatura tem esquema próprio** — exigir verificação real por provedor, sem "aceitar se não der para verificar". |
| **Replay** de webhook válido | M×M | Stripe grava `billing_events` por id único (idempotente). Exigir o mesmo: tabela de eventos de assinatura com id único do provedor. |
| **Fora de ordem** (ex.: "assinado" antes de "criado") | M×M | Derivar estado do evento mais recente por carimbo do provedor; nunca regredir um envelope "concluído". |
| Chave do webhook na URL (`/signatures/webhook/{provedor}/{chave}`) vaza em log | M×A | **Mascarar essa chave no log** (mesmo tratamento do token de download). A URL inteira não pode ir ao log de acesso. |
| Webhook dispara trabalho caro (download do PDF assinado) sem limite | M×M | Enfileirar; limitar tamanho do PDF baixado; validar que o envelope pertence a um workspace nosso antes de baixar. |

### 1.6 Credenciais de terceiros (D40)

| Ameaça | I×P | Estado |
|---|---|---|
| Token/chave do provedor em texto no banco | A×M | Spec exige **Fernet** (`cryptography` já instalado, v50). Exigir chave em `ENCRYPTION_KEY`/arquivo secreto, **nunca** no `.env` versionado. |
| Credencial de terceiro vaza em log/erro | A×M | O `SafeTextFormatter`/`JsonFormatter` já cortam mensagem de exceção e só aceitam chaves em allowlist (`SAFE_EXTRA_KEYS`). Exigir que `secret`, `api_key`, `token`, `webhook_secret` **não** entrem em `extra=` e que o "Testar conexão" não ecoe a credencial. |
| Credencial de um workspace usada por outro | A×B | `workspace_id` em `signature_providers`; segredo de webhook aleatório por workspace (a spec já define). |

### 1.7 SSRF (URLs de provedores/webhooks) — D40

| Ameaça | I×P | Estado |
|---|---|---|
| URL do provedor/base apontando para rede interna (169.254.169.254, localhost, 10/8) | A×M | **Não existe hoje.** Exigir: base URL do provedor **fixa no código** por adaptador (não configurável por workspace); se algum campo de URL vier do provedor (ex.: link de download do PDF assinado), validar host contra allowlist do provedor e **recusar IP privado/loopback/link-local** antes de buscar. Buscar PDF assinado só de host conhecido do provedor. |
| Redirecionamento do provedor para alvo interno | M×B | Desabilitar/limitar redirects no cliente httpx que baixa artefatos de terceiros. |

### 1.8 Enumeração, CSRF/CORS, XSS nas páginas públicas

| Ameaça | I×P | Estado |
|---|---|---|
| CSRF nas rotas públicas | B×M | Rotas de teste/link são sem sessão; o risco de CSRF clássico é baixo (não há cookie a abusar). O `check_origin` atual só exige Origin em métodos inseguros **quando há Origin**; manter, e **não** depender dele para anti-abuso. |
| CORS afrouxado para servir o widget do teste em domínio terceiro | M×M | Se o teste/landing precisar de origem cruzada, **não** liberar `*`; listar origens. Hoje tudo é mesma origem pelo rewrite do Next. |
| **XSS refletido na página do cliente `/r/{token}`** (nome do espaço, mensagem, rótulos de campo vindos do profissional; e, no resultado do teste, o conteúdo do documento do visitante) | A×M | **Páginas novas.** Exigir render React escapado (sem `dangerouslySetInnerHTML`), e a prévia do documento do teste **sanitizada** (o visitante controla 100% do conteúdo). A CSP hoje só tem `media-src 'self'` (next.config); para as páginas públicas, exigir CSP mais restritiva (sem `unsafe-inline` de script). |
| Conteúdo do documento do teste refletido no JSON e renderizado como HTML | A×M | Tratar trechos/`sample` dos campos como texto, nunca HTML. |

### 1.9 LGPD

| Ameaça | I×P | Estado |
|---|---|---|
| Visitante sobe documento com **dados pessoais de terceiros** no teste anônimo, e esses dados vão para a OpenRouter | A×A | Spec pede aviso ("não use dados de terceiros sem autorização", "apagado em 1 h"). Exigir: **retenção de 1 h com job de limpeza que roda de verdade**, `provider.data_collection=deny` (já é o padrão do cliente OpenRouter), e **não** reaproveitar o arquivo do teste fora do claim. É tratamento de dado pessoal sem base clara → manter o aviso e a retenção curtíssima. |
| Dados do cliente no link (`client_requests`) retidos além do necessário | M×M | Spec: retenção padrão 30 dias após respondido. Exigir expurgo automático e que a auditoria **não** grave os valores (o `audit.record` já descarta `values`/`cpf`/`email`). |
| Fotos de RG/CNH/comprovante enviadas pelo link ficam no storage | A×M | A D37 já regrava a foto sem metadados e não guarda; exigir o mesmo caminho no link e retenção curta do anexo. |

---

## 2. Requisitos priorizados para o engenheiro

Níveis: **OBR** = obrigatório antes de publicar a feature · **REC** = recomendado para o piloto · **DEP** = depois.
Cada um traz valor concreto (onde aplicar, número, como testar).

### Transversal (A e B dependem) — IP real do cliente

- **OBR-0 — `client_ip(request)` confiável com lista de proxies.** Em `core/deps.py`, trocar o
  "primeiro item do `X-Forwarded-For`" por: ler o XFF **da direita para a esquerda**, descartando endereços que
  pertençam a `TRUSTED_PROXIES` (padrão: loopback + redes Docker internas, ex. `127.0.0.1/8`, `10.0.0.0/8`,
  `172.16.0.0/12`), e usar o primeiro que **não** for confiável. Fora de um proxy confiável, usar `request.client.host`
  e **ignorar** o XFF. Trocar `--forwarded-allow-ips=*` no `Dockerfile` pela lista real de proxies. Garantir que o
  proxy do Next **sobrescreva** (não apenas acrescente) o `X-Forwarded-For` com o IP de origem, ou que o backend não
  confie no Next para isso. *Testar*: os testes de regressão `test_trial_security.py::test_client_ip_*` (já escritos,
  hoje `xfail`) + o PoC `scripts`/stress. Alvo: cadastro com XFF forjado **deve** dar 429 depois do limite.

### A — Teste grátis na landing (D38)

- **OBR-1 — Limites por IP e por faixa, contando TENTATIVAS (não sucessos).** 3/hora e 10/dia por IP real; 30/dia por
  /24 (IPv4) ou /64 (IPv6). Contar toda submissão aceita, inclusive as que terminam em falha da IA (senão, forçar
  `AI_TRUNCATED` fura o limite — confirmado no PoC). Aplicar em `POST /public/trials`, com o `client_ip` do OBR-0.
- **OBR-2 — `TRIAL_MAX_CONCURRENT` (padrão 3) global.** Acima disso, fila curta ou "tente em instantes". Impede que um
  pico sature o worker e multiplique chamadas de IA simultâneas.
- **OBR-3 — Budget diário de IA só do teste (`TRIAL_AI_DAILY_BUDGET_USD`, padrão 0,50).** Reservar pela finalidade
  nova `trial` (workspace nulo) no `ai_budget`, **antes** de chamar. Esgotou → segue só com regras locais, com aviso.
  A IA do teste lê no máximo **6.000 caracteres** (corta o texto antes de montar o prompt).
- **OBR-4 — Validação de upload do teste pelos caminhos existentes.** `.docx` por `validate_docx`; PDF **só** pelo
  `pdfconv` isolado; limite **5 MB e 10 páginas**; **nada de LibreOffice** (sem gerar PDF/DOCX no teste). Rejeitar
  imagem/arquivo fora de .docx/PDF.
- **OBR-5 — Isolar o budget do teste do budget dos clientes.** A reserva `trial` **não pode** consumir o
  `AI_MONTHLY_BUDGET_USD` que protege os clientes pagantes (ver seção 0: hoje o atacante esgotaria os US$ 20 e
  derrubaria a IA de todos). Opções: contador mensal separado para `trial`, ou checar o budget diário do teste **em
  vez** do mensal global para a finalidade `trial`. *Testar*: estourar o budget do teste **não** deve reduzir
  `actions_limit`/disponibilidade de IA de um workspace pagante.
- **REC-1 — Cloudflare Turnstile quando `TURNSTILE_SECRET_KEY` estiver setada.** Validar no servidor; sem a chave, o
  teste funciona e os limites por IP seguram. **Campo-armadilha** escondido (`website`): preenchido → responde sucesso
  falso e **não** processa (não gasta IA).
- **REC-2 — Retenção de 1 h real.** Job de limpeza (igual ao `cleanup`) apaga arquivo e resultado do teste; token de
  claim some junto. Aviso de privacidade curto na UI (spec).
- **REC-3 — Token do teste ≥ 256 bits, só hash no banco, 404 genérico** em `/public/trials/{token}`.

### B — Link para o cliente preencher (D39)

- **OBR-6 — Token de 32 bytes aleatórios, guardado só como hash; mostrado uma vez.** 404 genérico; validade padrão
  7 dias, máximo 30; expiração e cancelamento checados no servidor.
- **OBR-7 — Limite por IP e por token** em `/public/requests/{token}` (submissão e reenvio). Anexos pelos mesmos
  limites da D37 (4 arquivos, 8 MB, 50 Mpx, foto regravada sem metadados); no máximo 3 leituras por IA por link.
- **OBR-8 — XSS nas páginas públicas.** `/r/{token}` e a prévia do resultado do teste: React escapado, **sem**
  `dangerouslySetInnerHTML`; sanitizar a prévia do documento (o visitante/cliente controla o conteúdo). CSP das rotas
  públicas sem `script 'unsafe-inline'`. *Testar*: payload `<img onerror>`/`<script>` em nome do espaço, mensagem,
  rótulo e conteúdo do documento não executa.
- **OBR-9 — A página do cliente só expõe os rótulos dos campos pedidos.** Nada de outros valores, outros clientes ou o
  modelo além dos rótulos. Auditoria registra criação/abertura/envio/cancelamento **sem** os valores.
- **REC-4 — Retenção configurável (padrão 30 dias após respondido)** com expurgo automático; anexos com retenção curta.

### C — Assinatura eletrônica (D40)

- **OBR-10 — Verificação real de assinatura do webhook por provedor** (HMAC/segredo do provedor), no padrão do Stripe
  (`verify_webhook`): tolerância de tempo, corpo limitado, **recusar** se não der para verificar. Rota
  `/signatures/webhook/{provedor}/{chave}`.
- **OBR-11 — Idempotência e ordem do webhook.** Gravar o id do evento do provedor numa tabela com id único (como
  `billing_events`); reenvio = no-op; nunca regredir um envelope "concluído" por evento fora de ordem.
- **OBR-12 — Credenciais do provedor cifradas (Fernet), chave fora do repositório.** Nunca em `.env` versionado; nunca
  em log; "Testar conexão" não ecoa a credencial. Segredo de webhook aleatório por workspace. Mascarar a `{chave}` da
  URL do webhook no log.
- **OBR-13 — Anti-SSRF.** Base URL de cada provedor **fixa no código** (não por workspace). Qualquer URL vinda do
  provedor (ex.: link do PDF assinado) validada contra o host do provedor e **recusando** IP privado/loopback/
  link-local; redirects limitados no httpx que baixa artefatos.
- **REC-5 — Consulta periódica no worker como reserva** do webhook (a spec já prevê), com limite de tamanho do PDF
  baixado e verificação de que o envelope pertence a um workspace nosso.
- **DEP-1 — Verificação PAdES/ICP-Brasil** (gov.br assistido) só no `pdfconv` isolado, nunca abrindo o PDF de fora na
  API (D35). Já é fase posterior.

### Transversal

- **REC-6 — Apertar a estimativa de tokens de PDF em `fill-files`** (`_attachment`): hoje subestima ~46× para PDF de
  muitas páginas. Limitar páginas do PDF enviado à IA e/ou estimar por página real.
- **DEP-2 — CSP completa com nonce** (item 16 do BACKLOG): necessária para endurecer as páginas públicas de verdade.

---

## 3. Provas de conceito executadas (stack local, IA falsa)

Todas contra `http://127.0.0.1:8160` (e `:3360` pelo Next), com a IA falsa `scripts/fake_openrouter.py` em
127.0.0.1:8169. **Zero IA real.**

1. **`X-Forwarded-For` fura o limite de cadastro** — 12 cadastros com XFF variável → 12×201 (sem XFF: 429 no 11º).
   Pelo Next (:3360) o XFF forjado também passa. → OBR-0.
2. **Login: 30 IPs forjados nunca travam a conta** — 30 logins errados com 30 XFF → nenhum bloqueio por conta. → OBR-0.
3. **Falha de IA queima o teto sem descontar cota** — 50 chamadas com a IA em modo "cortada" (`AI_TRUNCATED`):
   `actions_used` ficou em 1, mas o `ai_spend` somou US$ 0,2654 em linhas `failed`. → OBR-1 (contar tentativas) e OBR-5.
4. **Modelo de custo do teste** — medido o pior caso por chamada (US$ 0,0233) e o custo real (~US$ 0,0015); tabelas da
   seção 0.
5. **Memória/CPU de upload** — `.docx` de 1,1 MB → 78 MB descomprimido: parse 6,7 s / +523 MB. PNG 49 Mpx: 0,9 s /
   +508 MB por arquivo (×4). PDF de 1.000 páginas: reserva subestima 46× os tokens reais. → casos 1.2 e REC-6.

Os testes de regressão de segurança ficam em `backend/tests/test_trial_security.py` (marcados `xfail` enquanto o
código das features não chega). O script da IA falsa e os de estresse ficam em `scripts/`.

---

## 4. Fase 2 — revisão da D38 (teste grátis) e do IP real (e1e6d5e + b1968ac)

Revisado linha a linha e testado no stack local (API 8160 com `--no-proxy-headers`, Next 3360, IA falsa). Sem IA real.

**Verificado e OK**
- IP real: pelo Next, com `X-Forwarded-For` forjado de 2 saltos diferente a cada envio → 3 testes aceitos e o 4º/5º com 429.
  O Next acrescenta o IP do socket; a API lê só `TRUSTED_PROXY_HOPS` entradas da direita.
- Custo: o `trial` fica fora do teto mensal dos clientes (OBR-5) e falhas forçadas da IA continuam contando no teto
  diário do teste (teste `test_falha_da_ia_conta_no_teto_diario_do_teste_e_nao_no_mensal`). Limites contam tentativas.
  Fila `trial` sem retry. 3 testes → 3 chamadas à IA falsa.
- Token: 32 bytes, só hash, regex, 404 igual para inexistente/expirado/guardado, 120 consultas/min por IP.
- Claim: `UPDATE ... WHERE claimed_at IS NULL` atômico; outra conta recebe 404 (`test_teste_ja_guardado_nao_pode_ser_tomado_por_outra_conta`).
- Uploads: `Content-Length` checado antes de ler; .docx com 300 partes / 15 MB por parte / 25 MB no total; PDF só pelo
  `pdfconv`, 10 páginas. Pelas medições da fase 1, 25 MB descompactados custam ~1 s e ~170 MB no parse.
- XSS/CSP: a prévia renderiza o documento como texto pelo React; CSP com nonce servida em `/` e `/r/*`.
- Limpeza: `purge_expired_trials` roda pelo watchdog de cada worker (e da API no modo thread) → arquivo e linha somem
  em até ~TTL + 5 min.

**Achados**

| # | Gravidade | Achado | Correção sugerida |
|---|---|---|---|
| F2-1 | **Média** | O log de acesso grava `/api/v1/public/trials/{token}` (a cada consulta) e `/trials/{token}/claim` com o token em claro. Confirmado no log local. O token dá acesso ao documento inteiro do visitante (possíveis dados de terceiros) por até 1 h, e logs costumam ir para serviços externos e durar mais. | Em `core/logging.py`, generalizar a máscara de `/downloads/` para `/public/trials/`, `/trials/`, `/public/requests/` e `/signatures/webhook/{provedor}/`. Regressão: `test_token_do_teste_nao_vai_para_o_log` (xfail estrito até corrigir). |
| F2-2 | Baixa (implantação) | `TRUSTED_PROXIES` padrão inclui `10.0.0.0/8` e `172.16.0.0/12`: quem alcançar a API direto de dentro dessas redes escolhe o próprio IP. Com balanceador/Caddy na frente do Next e `TRUSTED_PROXY_HOPS=1`, todos os visitantes viram o IP do balanceador (3 testes/h para o site inteiro). | Em produção, restringir à sub-rede do compose (ou ao IP do Next) e, com proxy de borda, `TRUSTED_PROXY_HOPS=2` + IP da borda na lista. Pôr no checklist de implantação. |
| F2-3 | Baixa (disponibilidade) | Muitos celulares no Brasil saem por CGNAT (um IPv4 para muita gente): 3/h por IP pode barrar visitantes legítimos. `TRIAL_MAX_CONCURRENT=3` é fácil de ocupar para negar o teste aos outros (sem custo). | Com o Turnstile validado, permitir limite maior por IP; fila curta em vez de `TRIAL_BUSY` imediato; Turnstile ligado em produção. |
| F2-4 | Baixa | A trava da reserva só existe no PostgreSQL; no SQLite (modo sem Docker) reservas simultâneas podem passar do teto diário. | Produção é PostgreSQL: só documentar. |
| F2-5 | Info | A resposta da armadilha (`website`) não tem `expires_at` e o token dela dá 404: um robô consegue perceber a armadilha. | Opcional: mesma forma da resposta real. |

### 4.1 Verificação das correções (0091fbc)

Conferido no stack local, pelo Next, sem IA real. Os testes `test_security_phase2.py`, `test_trial_security.py`,
`test_trials.py`, `test_client_ip.py` e `test_apply_fields.py` passam; o único `xfail` restante é o placeholder de `/r/{token}` (D39).

- **F2-1 resolvido**: depois de consultas e de um claim pelo Next, 0 tokens em claro no log da API e os caminhos
  aparecem como `/public/trials/[token]` e `/trials/[token]/claim`. A máscara cobre também `/public/requests/` e
  `/signatures/webhook/{provedor}/`.
- **F2-5 resolvido**: a armadilha devolve as mesmas chaves (`token`, `status`, `expires_at`), passa por `processing` e
  termina em `failed`/`TRIAL_FAILED`, conta no limite por IP (o 4º envio da hora deu 429) e não ocupa vaga. As linhas
  ficam sem arquivo, limitadas pelos mesmos tetos (10/dia por IP, 30/dia por /24) e somem com a limpeza. Resta uma
  diferença menor (informativo): a armadilha decide antes de validar o arquivo e grava `documento.docx`/`docx`. Um robô
  que mande lixo com o campo preenchido recebe 202 em vez de 400. Opcional: chamar `_check_file` antes e guardar o nome e
  o formato reais.
- **F2-3, regras novas**: com o Turnstile aprovado sobe só o limite por hora por IP (6); o diário por IP, o de /24 e o
  orçamento diário da IA não mudam, então o caminho verificado não fura nenhum dos dois. A espera de até 5 s ocupa uma
  thread do pool síncrono da API (compartilhado com as demais rotas, ~40 por processo), mas só depois da tentativa contada
  e do arquivo validado: no máximo 3 (6 verificadas) por IP por hora. Para prender o pool seria preciso manter ~8 esperas
  por segundo, ou seja, milhares de IPs por hora. Risco baixo. Melhoria opcional: esperar com `asyncio.sleep` na rota ou
  limitar as esperas simultâneas (ex.: 10) e responder `TRIAL_BUSY` acima disso.
- **QA-4**: teto de 300 achados e a prévia montada por `apply_fields`, que gera os mesmos nós JSON com `sample` como
  texto. O front não mudou, então a prévia continua sem HTML.
