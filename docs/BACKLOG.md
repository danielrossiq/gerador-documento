# Backlog técnico — Fases 3/5 (estratégia provisória)

Estratégia provisória ([ESTRATEGIA_COMERCIAL.md](ESTRATEGIA_COMERCIAL.md), D29): **escritórios pequenos de advocacia (1–5 pessoas)**, **self-service** (a pessoa se cadastra e usa sozinha), "Minuta" como nome de trabalho; sem gastos, cobrança ou publicação. Meta do piloto: primeiro documento em até 5 min (ativação) e retorno em D7. Este backlog traduz isso no que o código precisa ter, ordenado por valor ÷ (risco × esforço).

Baseline (15/10/2026, branch `claude/blissful-pasteur-hvkev9`, ver README "Resultados verificados — Fase 0"):
- pytest 293 passed (273 da Fase 0 + 12 do item 1 + 8 do item 2);
- vitest 98 passed;
- tsc, build e ruff sem erros; eslint com 0 erros e 15 avisos;
- E2E no Edge 16/16 na stack Docker `minuta-fase0`, reconstruída com os itens 1 e 2.

Escalas usadas abaixo:
- **Valor**: A = destrava uso por advogados; M = melhora; B = conforto.
- **Risco**: A = mexe em área sensível e exige Security review antes; M = toca dados ou geração; B = local e reversível.
- **Esforço**: P ≤ 1 dia; M ≤ 1 semana; G > 1 semana.
- **Gate**: o que precisa acontecer antes de começar.

## Agora (baixo risco, sem depender do design)

| # | Item | Valor | Risco | Esforço | Depende de | Gate | Critério de aceite |
|---|---|---|---|---|---|---|---|
| 1 | **Valor por extenso** ("R$ 1.500,00 (mil e quinhentos reais)") — **feito** (3d41964) | A | B | P | — | — | Opção "Como o valor sai no documento" no campo Valor. Mesmo texto no servidor e na prévia, garantido pelos vetores compartilhados. Documento gerado contém o extenso (`test_currency_in_words_goes_to_the_document`). |
| 2 | Sugestão automática reconhece "R$ X (por extenso)" no documento enviado e já cria o campo com extenso — **feito** | A | M (motor de regras, não IA; decidido: não é "parser" para o gate) | P | 1 | — | Contrato com "R$ 5.000,00 (cinco mil reais)" vira **um** campo Valor com `currency_format=words`, e o texto entre parênteses é substituído junto. Sem regressão em `test_suggestion_rules.py`. |
| 3 | Data por extenso "jurídica" ("aos 21 dias do mês de setembro de 2026" / ano por extenso) | M | B | P | — | — | Nova opção em `date_format`, coberta pelos vetores compartilhados. |
| 4 | Listas prontas para qualificação das partes (estado civil, nacionalidade, profissão, regime de bens), sugeridas no editor | M | B | P | — | — | Selecionar "solteiro(a)" sugere o tipo Lista de opções já preenchido. Tudo local, sem IA. |
| 5 | Tipo de campo **OAB** (UF + número) com validação de formato | M | B | P | — | — | Aceita "OAB/ES 12.345" e "ES 12345"; recusa UF inválida. Vetores compartilhados. |

### Item 2 — riscos e evidências
- **Processamento local**: a regra roda em `suggestions/rules.py`, que são funções puras sobre o texto do bloco. Não faz chamada de rede, não usa IA e não grava telemetria; o texto do documento continua só no banco do workspace. `test_currency_words_suggestion.py` bloqueia `socket.connect`/`create_connection`/`getaddrinfo` durante a detecção e durante o upload com análise.
- **Falso positivo**: só captura o parêntese logo depois do valor quando ele termina em real/reais/centavo(s) e só tem letras, espaços, vírgulas e hífen. "(cláusula 3)" e "(ver anexo I)" ficam fora (testados).
- **Extenso do documento que não confere com o valor** (ex.: "R$ 5.000,00 (seis mil reais)"): vira o mesmo campo e o motivo da sugestão avisa que o documento gerado terá o extenso correto. Nada é corrigido em silêncio no original.
- **Cache de análise**: `RULES_VERSION` passou de r2 para r3, então documentos reanalisados recebem a regra nova. Análises antigas não mudam sozinhas.
- **Exemplo do campo**: guarda só o valor ("R$ 5.000,00"), para a prévia e o "Preencher com dados de exemplo" continuarem válidos.
- **Evidência**:
  - pytest 293 passed;
  - E2E `extenso.spec.ts` no Edge: upload → sugestão → aceitar → prévia → formato no campo;
  - suíte E2E completa 16/16 na stack `minuta-fase0` reconstruída.

## Próximo (precisam do handoff de design)

| # | Item | Valor | Risco | Esforço | Depende de | Gate | Critério de aceite |
|---|---|---|---|---|---|---|---|
| 6 | **Biblioteca de modelos jurídicos** (procuração ad judicia, contrato de honorários, substabelecimento, declaração de hipossuficiência) como "Experimentar com um exemplo" | A | B/M (textos precisam de revisão jurídica) | M | design (galeria), revisão jurídica | revisão de conteúdo | Cada modelo gera DOCX e PDF válidos, com campos e extenso. Avisa que é exemplo, não orientação jurídica. |
| 7 | **Cláusulas condicionais** (bloco que aparece por Sim/Não) | A | M (parser/compilador DOCX) | G | design do editor | Security review: muda o parser | Bloco marcado some ou aparece no DOCX e no PDF sem quebrar numeração nem estilos; testes de compilação para tabela, lista e cabeçalho. |
| 8 | **Partes repetíveis** (N outorgantes/réus) | A | M (parser) | G | 7 | Security review | Gera N blocos de qualificação; lote e kit continuam funcionando. |
| 9a | **Instrumentação de ativação sem conteúdo** (`template_upload_started/completed`, `first_generation_completed`, tempo até o 1º documento, lote, retorno D7/D30) gravada localmente, com IDs pseudônimos | A (mede a meta do piloto) | M (dados de uso, LGPD) | M | — | Security review (privacidade/retenção) | Nenhum evento carrega texto do documento, valores de campo, nome ou e-mail; retenção documentada; relatório local de ativação. |
| 9 | Onboarding self-service orientado a escritório (perfil "advocacia" no cadastro) | M | M (toca cadastro) | M | design | Security review (auth) | Sem mudar o modelo de sessão ou permissões; só conteúdo inicial. |

## Depois (área sensível — só depois de Security review)

| # | Item | Valor | Risco | Esforço | Gate |
|---|---|---|---|---|---|
| 10 | Cobrança/planos (cota hoje é só limite técnico, `PLAN_LIMITS`) | A (negócio) | A | G | Security review + decisão de provedor (custo) |
| 11 | Convites e equipe no escritório (multi-usuário no mesmo workspace) | A | A (multitenancy/auth) | G | Security review |
| 12 | E-mail transacional real (hoje só recuperação de senha via SMTP opcional) | M | A (terceiro) | M | Security review + escolha de provedor |
| 13 | Retenção e LGPD para escritórios (sigilo profissional: prazo configurável, **exportação e exclusão do workspace sob demanda**, registro de acesso) — pré-requisito do piloto com documentos reais | A | A | M | Security review |
| 14 | Assinatura eletrônica | M | A (terceiro) | G | Security review + custo |
| 15 | OCR para PDF digitalizado (hoje recusado de propósito, D28) | M | A (uploads/parser) | G | Security review |

## Pendências conhecidas da baseline
- Não reexecutados nesta fase: pytest contra PostgreSQL real, lote de 1.000 e `scripts/crash_recovery_test.py`.
- O cadastro tem limite de 10 por hora por IP, e a suíte E2E cria cerca de 7 contas por execução (README).
