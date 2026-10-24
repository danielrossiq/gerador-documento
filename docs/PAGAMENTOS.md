# Pagamentos: como ativar a cobrança (Stripe)

O código de cobrança já está pronto e testado (D34). Falta só a conta na Stripe e algumas variáveis no servidor.
Enquanto `BILLING_ENABLED=false`, ninguém é cobrado e todos usam os limites padrão. A tela **Plano e uso**
(`/assinatura`) mostra "período de lançamento".

## Situação (24/10/2026)

**Modo teste configurado e testado de ponta a ponta.** A conta Stripe está criada, na área restrita "MINUTA". Os produtos, os 4 preços e o portal do cliente foram criados por `scripts/stripe_setup.py`. No teste, um checkout com o cartão `4242` voltou ao app com o plano Profissional ativo na hora, mostrou "Renova em 24/11/2026" e o portal abriu com a fatura paga.

- A chave de teste fica em `~/.minuta/stripe-test.key`, legível só pelo usuário, e entra no stack como secret:

  ```bash
  STRIPE_KEY_PATH=~/.minuta/stripe-test.key STRIPE_WEBHOOK_SECRET_PATH=~/.minuta/stripe-webhook.secret     docker compose -f docker-compose.yml -f docker-compose.ai.yml -f docker-compose.billing.yml up -d
  ```

- **Sem webhook no `localhost`:** a volta do checkout chama `/billing/sync`, que consulta a sessão direto na Stripe com a nossa chave e ativa o plano. Renovação, cancelamento pelo portal e falha de pagamento precisam do webhook real, que só existe em produção (passo 5). O segredo em `~/.minuta/stripe-webhook.secret` é provisório e só serve localmente.
- **Para produção:**
  1. Ativar a conta (dados e banco).
  2. Gerar uma chave restrita `rk_live_…`.
  3. Rodar `python scripts/stripe_setup.py --key-file CAMINHO --live --site https://SEU_DOMINIO`.
  4. Criar o webhook (passo 5) e gravar o `whsec_…` no arquivo do secret.

  Os passos 3 a 6 abaixo explicam o que o script faz, caso prefira fazer pelo painel.
- **Pix:** quando a Stripe liberar, crie no painel uma configuração de formas de pagamento só com Pix e coloque o `pmc_…` em `STRIPE_PIX_PAYMENT_METHOD_CONFIGURATION`. Assim, o botão "Pagar com Pix" não oferece cartão.

## Por que Stripe

- O realoficial.com.br usa **Stripe** para cartão. O próprio app deles tem os textos "Acessar Portal Stripe" e
  "Valor final na Stripe". O Pix deles é um fluxo à parte, renovado à mão, e não dá para saber qual provedor usam.
- Na Stripe, a mesma conta faz assinatura recorrente no cartão, Pix avulso, portal do cliente (trocar plano,
  cancelar, atualizar cartão, baixar recibos) e webhooks assinados. Não tem mensalidade.
- **Limite da Stripe no Brasil:** contas brasileiras só têm **Pix de pagamento único**. O Pix Automático
  (recorrente) não está disponível para empresas domiciliadas no Brasil. Por isso o Minuta trata o Pix como
  **período pré-pago** (1 mês ou 12 meses). Pagar um novo Pix antes do fim soma ao período atual. Esse é o mesmo
  modelo do realoficial.

## Passo a passo (você faz uma vez)

### 1. Criar e ativar a conta

1. Crie a conta em <https://dashboard.stripe.com/register> com país **Brasil**.
2. Em **Ativar pagamentos**, informe:
   - **Tipo de negócio:** pode ser **pessoa física (CPF)**. CNPJ é opcional. Um MEI ajuda a emitir nota fiscal, mas
     a Stripe não exige.
   - **Endereço comercial no Brasil.**
   - **Conta bancária no mesmo CPF (ou CNPJ) do titular.** A Stripe recusa conta de terceiros.
   - **Documento de identidade** e dados do representante.
   - **Site:** a URL pública da landing. Ela precisa estar no ar com preços, termos (`/termos`), privacidade
     (`/privacidade`) e um contato. Já existem as três páginas, mas o texto dos termos e da privacidade é
     preliminar e precisa de revisão jurídica antes do go-live.
   - **Descrição na fatura:** por exemplo `MINUTA DOCS`, como o cliente vai ver no extrato.
3. Ative a **verificação em duas etapas** na sua conta Stripe.

### 2. Pedir o Pix (opcional, por convite)

Em **Configurações › Formas de pagamento**, procure **Pix** e solicite. Hoje a Stripe libera o Pix por convite e
análise. Enquanto não for liberado, deixe `BILLING_PIX_ENABLED=false`: a tela de planos mostra só o cartão.

### 3. Criar os produtos e os 4 preços

Em **Catálogo de produtos › Adicionar produto**:

| Produto | Preço | Tipo | Variável |
|---|---|---|---|
| Minuta Profissional | R$ 49,90 | recorrente, **mensal** | `STRIPE_PRICE_PROFISSIONAL_MENSAL` |
| Minuta Profissional | R$ 478,80 | recorrente, **anual** (R$ 39,90/mês) | `STRIPE_PRICE_PROFISSIONAL_ANUAL` |
| Minuta Escritório | R$ 99,90 | recorrente, **mensal** | `STRIPE_PRICE_ESCRITORIO_MENSAL` |
| Minuta Escritório | R$ 958,80 | recorrente, **anual** (R$ 79,90/mês) | `STRIPE_PRICE_ESCRITORIO_ANUAL` |

Copie o ID de cada preço (`price_…`). O Pix não usa esses IDs: o valor sai de `plans.json`, o mesmo arquivo que
alimenta a landing. Se mudar um preço, mude nos dois lugares, `frontend/src/content/plans.json` e
`backend/app/modules/billing/plans.json`. Um teste confere que os dois arquivos batem.

### 4. Configurar o portal do cliente

Em **Configurações › Billing › Portal do cliente**:

- permita **cancelar assinatura**, no fim do período;
- permita **trocar de plano** entre os 4 preços acima;
- permita **atualizar forma de pagamento** e **ver faturas**.

### 5. Criar o webhook

Em **Desenvolvedores › Webhooks › Adicionar endpoint**:

- **URL:** `https://SEU_DOMINIO/api/v1/billing/webhook`
- **Eventos:**
  - `checkout.session.completed`
  - `checkout.session.async_payment_succeeded` (Pix pago depois)
  - `customer.subscription.created`
  - `customer.subscription.updated`
  - `customer.subscription.deleted`
  - `invoice.payment_failed`

Copie o **segredo de assinatura** (`whsec_…`). O servidor confere a assinatura HMAC de cada evento e recusa
eventos com mais de 5 minutos. Eventos repetidos são ignorados, porque cada evento é registrado uma vez.

### 6. Chave da API

Em **Desenvolvedores › Chaves de API**, prefira uma **chave restrita** com permissão de escrita em:

- Checkout Sessions
- Customer portal
- Customers

A chave secreta padrão também funciona.

### 7. Variáveis no servidor

No `.env` do servidor (nunca no repositório):

```
BILLING_ENABLED=true
BILLING_PIX_ENABLED=false          # true só depois que a Stripe liberar o Pix
STRIPE_SECRET_KEY=rk_live_…        # ou sk_live_…
STRIPE_WEBHOOK_SECRET=whsec_…
STRIPE_PRICE_PROFISSIONAL_MENSAL=price_…
STRIPE_PRICE_PROFISSIONAL_ANUAL=price_…
STRIPE_PRICE_ESCRITORIO_MENSAL=price_…
STRIPE_PRICE_ESCRITORIO_ANUAL=price_…
PUBLIC_WEB_URL=https://SEU_DOMINIO  # volta do checkout: /assinatura?status=sucesso
```

Reinicie `api` e `worker`.

## Testar antes de cobrar de verdade

1. No painel, ligue o **modo de teste** e repita os passos 3 a 6. Os IDs começam com `price_…`, as chaves com
   `sk_test_…`/`rk_test_…`.
2. Localmente, use a [Stripe CLI](https://docs.stripe.com/stripe-cli) para receber o webhook:

   ```bash
   stripe listen --forward-to localhost:8110/api/v1/billing/webhook
   ```

   A CLI mostra um `whsec_…` próprio. Use esse valor em `STRIPE_WEBHOOK_SECRET` enquanto testa.
3. Em `/assinatura`, assine com o cartão de teste `4242 4242 4242 4242`, qualquer validade futura e qualquer CVC.
   Ao voltar, a página espera a confirmação e mostra o novo plano.
4. Confira estes cenários:
   - **Gerenciar assinatura:** abre o portal; troque de plano e cancele.
   - **Cartão recusado:** use `4000 0000 0000 0341`. A assinatura fica com pagamento pendente e há 7 dias de
     tolerância antes de voltar ao Grátis.
   - **Pix**, se liberado: o checkout de teste simula o pagamento.

## Taxas

Valores consultados em out/2026. Confira em <https://stripe.com/br/pricing>.

- **Cartão nacional:** 3,99% + R$ 0,39 por transação.
- **Stripe Billing** (assinaturas recorrentes): + 0,7% do volume recorrente.
- **Pix:** 1,19% por transação.
- **Sem mensalidade nem taxa de adesão.** O repasse vai para a conta bancária cadastrada.

Exemplo: no Profissional mensal (R$ 49,90) a Stripe fica com cerca de R$ 2,73 e sobram cerca de R$ 47,17.

## Checklist de go-live

- [ ] Conta Stripe ativada, com conta bancária verificada e 2FA ligado
- [ ] Termos e privacidade revisados (hoje estão marcados como preliminares)
- [ ] Produtos e preços criados no **modo produção**, com os IDs no `.env`
- [ ] Webhook de produção criado, com o `whsec_…` no `.env`
- [ ] Portal do cliente configurado
- [ ] `PUBLIC_WEB_URL` com o domínio real (https) e `COOKIE_SECURE=true`
- [ ] Uma assinatura real de R$ 49,90 feita e cancelada pelo portal, para conferir o fluxo completo
- [ ] `BILLING_ENABLED=true` (e `BILLING_PIX_ENABLED=true` se a Stripe liberou o Pix)

## O que o código faz

| Parte | Onde |
|---|---|
| Planos e limites | `backend/app/modules/billing/plans.json` (cópia de `frontend/src/content/plans.json`) |
| Plano efetivo e limites | `billing/service.py`: `effective_plan`, `workspace_plan_limits`. Precedência: limite manual do espaço > plano > padrão |
| Checkout e portal | `billing/service.py`: `create_checkout` (cartão = assinatura; Pix = pagamento avulso com `price_data`), `create_portal` |
| Webhook | `billing/router.py`: `/billing/webhook` (HMAC, tolerância de 300 s, 1 MB). Idempotência pela tabela `billing_events` |
| Tela | `frontend/src/app/(app)/assinatura/page.tsx` (menu do usuário › Plano e uso) |
| Testes | `backend/tests/test_billing.py` |
