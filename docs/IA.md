# IA no DocFeito

A IA cuida da parte manual do trabalho com documentos. A pessoa continua no controle: a IA **sugere**, a pessoa
**confere**. Sem a chave, ou com `EXTERNAL_AI_ENABLED=false`, tudo funciona só com as regras locais e nada sai
do servidor.

## O que a IA faz

| Recurso | Onde aparece | Dor que resolve | Modelo |
|---|---|---|---|
| **Achar os campos** no documento enviado | Ao enviar um modelo, na etapa *Campos*: "Campos encontrados pela IA" | Marcar à mão nome, CPF, valores e datas num contrato de 10 páginas | Claude Haiku 5.5 |
| **Preencher com IA** | Tela *Gerar*, de um documento ou de um kit: "Cole o e-mail, o WhatsApp ou a ficha do cliente" | Copiar e colar campo por campo o que o cliente mandou por mensagem | Gemini 2.5 Flash |
| **Preencher com a foto dos documentos** | Tela *Gerar*, aba "Foto ou PDF" do Preencher com IA | Digitar à mão nome, CPF, RG, endereço e CEP a partir da foto do RG/CNH e da conta de luz que o cliente mandou | Gemini 2.5 Flash (ver D37) |
| **Revisar com IA** | Tela *Gerar*, ao lado de "Gerar documento" | Erros que passam batido: término antes do início, "inscrita" para um homem, valor por extenso diferente do número, nome escrito de dois jeitos | Gemini 2.5 Flash |

### Garantias

- **Não inventa.** O "preencher" só aceita um valor se o trecho citado como evidência, ou o próprio valor, estiver
  no texto colado. A comparação ignora acento e pontuação, e para CPF, CNPJ, telefone e datas numéricas compara só
  os dígitos. Se um modelo "completar" um campo com algo que não estava no texto, o valor é descartado e o campo
  fica em branco. Teste: `test_grounding_accepts_reformatted_values_and_rejects_invented_ones`.
- **Valida igual à geração.** Cada valor preenchido passa pela mesma validação do formulário (CPF, data, valor…).
  Valor inválido vai para o campo marcado em vermelho.
- **A revisão não altera nada.** Ela só aponta o que conferir, com o link "Ir para o campo". Não comenta redação
  jurídica nem dá aconselhamento.
- **Privacidade.** Vai para a IA só o necessário: os rótulos dos campos e o texto colado, ou o texto do documento
  com os valores. A razão de custo (`ai_spend`) guarda só workspace, finalidade, modelo, tokens e custo, sem
  conteúdo. Todas as chamadas pedem à OpenRouter **provedores que não guardam nem treinam com os dados**
  (`provider.data_collection = "deny"`).

## Escolha dos modelos (custo × acerto)

Tudo foi medido com a chave real, em 21/10/2026.

### Achar campos

Conjunto ouro com 15 documentos fictícios de 8 categorias (`app/eval/gold.py`). Cada modelo roda junto com as
regras determinísticas, como no app. Relatório completo em [ai/avaliacao-modelos.md](ai/avaliacao-modelos.md).

| Modelo | Recall | Precisão | Custo/doc | Tempo |
|---|---:|---:|---:|---:|
| Só regras locais (sem IA) | 53,5% | 78,6% | 0 | — |
| Gemini 2.5 Flash-Lite | 84,3% | 90,1% | US$ 0,00045 | 2,9 s |
| GPT-5.6 Luna | 91,3% | 92,4% | US$ 0,00112 | 7,0 s |
| **Claude Haiku 5.5** | **91,9%** | **94,0%** | **US$ 0,00091** | 6,8 s |
| Claude Sonnet 5 | 91,9% | 93,5% | US$ 0,01300 | 8,2 s |
| DeepSeek V4.1 Flash | 70,3% | 91,7% | US$ 0,00153 | 9,7 s, 3 falhas |
| Mistral Small | 64,0% | 89,4% | US$ 0,00133 | 13,2 s, 6 falhas |
| GPT-5 nano | 43,6% | 89,3% | US$ 0,00165 | 37,6 s, 15 falhas |

**Escolhido: Claude Haiku 5.5.** Tem o mesmo acerto do Sonnet 5 por 1/14 do custo, e o recall é +38 pontos sobre as
regras sozinhas. A análise roda no worker, uma vez por modelo enviado, então os ~7 s não travam ninguém.

> Lição da avaliação: modelos que "raciocinam" (Haiku 5.5, GPT-5…) gastam tokens pensando antes de responder.
> Com teto de saída apertado, o JSON vinha cortado. Na 1ª rodada isso derrubou o Haiku a 67% de recall. Agora o
> teto tem folga (`max_output_tokens`) e uma resposta cortada vira o erro `AI_TRUNCATED`, em vez de "JSON
> inválido".

### Preencher (texto colado → campos)

Três textos realistas: um e-mail, uma conversa de WhatsApp e uma ficha cadastral, com 19 valores esperados.

| Modelo | Acertos | Inventados | Tempo | Custo/texto |
|---|---:|---:|---:|---:|
| Gemini 2.5 Flash-Lite | 18/19 | 0* | 2,0 s | US$ 0,00025 |
| Claude Haiku 5.5 | 19/19 | 0 | 4,7 s | US$ 0,00050 |
| **Gemini 2.5 Flash** | **19/19** | **0** | **2,7 s** | **US$ 0,00104** |

\* Antes da checagem de evidência, o Flash-Lite escolheu um "tipo de serviço" da lista sem nada no texto.

### Revisar

Um contrato com 4 erros plantados: gênero trocado, término antes do início, extenso diferente do número e
sobrenome divergente. Todos os modelos acharam os 4. O que muda é o falso alarme:

- **Gemini 2.5 Flash**: 4/4, sem falso alarme, cerca de 2,7 s, US$ 0,0008.
- Flash-Lite: 4/4, mas também apontou "assinatura antes do início", que é normal.
- Haiku 5.5 e GPT-5.6 Luna: 4/4, porém com 6–7 s.

**Escolhido: Gemini 2.5 Flash** para preencher e revisar. A pessoa está esperando na tela, então rapidez também
conta.

## Custos e travas

| Trava | Padrão | O que faz |
|---|---|---|
| `EXTERNAL_AI_ENABLED` | `false` | Desligado, nada sai do servidor |
| `AI_MAX_CALL_USD` | 0,05 | Antes de cada chamada, o custo máximo possível (tokens de entrada + teto de saída × preço) precisa caber aqui |
| `AI_MONTHLY_BUDGET_USD` | 20 | Teto do mês somando todos os espaços. Ao atingir, a análise volta às regras locais e "preencher/revisar" avisa |
| Cota do plano | Grátis 5 · Profissional 100 · Escritório 500 usos/mês | Cada análise, preenchimento ou revisão conta um uso. Falhas não contam |
| `TRIAL_AI_DAILY_BUDGET_USD` | 0,50 | Teto **diário** do teste grátis da landing (finalidade `trial`, D38), separado do mensal: o gasto do teste não entra no `AI_MONTHLY_BUDGET_USD` dos clientes. Esgotou → o teste segue só com as regras locais. A IA do teste lê só os primeiros 6.000 caracteres |

A reserva do custo é feita **antes** da chamada, com trava no banco (`pg_advisory_xact_lock`), então chamadas
simultâneas não estouram o teto. Depois, o custo real informado pela OpenRouter substitui a reserva.

**Ordem de grandeza:** um escritório que analisa 20 modelos e faz 300 preenchimentos e revisões por mês gasta cerca
de US$ 0,35 (≈ R$ 2). A cota do plano existe para conter abuso, não por causa do custo.

## Como ligar

A chave da OpenRouter **nunca** vai para o `.env` nem para o repositório. Ela fica num arquivo do usuário
(`~/.minuta/openrouter.key`, legível só por ele) e entra no stack como *secret* do Docker:

```bash
OPENROUTER_KEY_PATH=~/.minuta/openrouter.key docker compose -f docker-compose.yml -f docker-compose.ai.yml up -d
```

O `docker-compose.ai.yml` liga `EXTERNAL_AI_ENABLED=true`, `AI_PROVIDER=openrouter` e monta a chave em
`/run/secrets/openrouter_key` na API e no worker.

Para reavaliar os modelos quando sair um modelo novo (custa centavos e tem teto):

```bash
cd backend
python -m app.cli ai-eval models --models anthropic/claude-haiku-5.5,google/gemini-2.5-flash --budget 1.5 --md ../docs/ai/avaliacao-modelos.md --json ../docs/ai/avaliacao-modelos.json
```

## Código

| Parte | Onde |
|---|---|
| Cliente OpenRouter (JSON estrito, erros com código estável, sem `temperature`) | `backend/app/adapters/ai/openrouter.py` |
| Reserva e liquidação de custo, cota | `backend/app/modules/ai_budget.py` |
| Chamada com trava e escolha do modelo por finalidade | `backend/app/modules/assist/ai.py` |
| Preencher e revisar | `backend/app/modules/assist/service.py` |
| Telas | `frontend/src/components/assist/ai-assist.tsx` |
| Testes (sem rede) | `backend/tests/test_assist_ai.py` e `frontend/e2e/assist-billing.spec.ts` (este com a IA real, quando ligada) |
