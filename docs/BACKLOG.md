# Backlog técnico — Fases 3/5 (estratégia provisória)

Estratégia provisória ([ESTRATEGIA_COMERCIAL.md](ESTRATEGIA_COMERCIAL.md), D29): **escritórios pequenos de advocacia (1–5 pessoas)**, **self-service** (a pessoa se cadastra e usa sozinha), "Minuta" como nome de trabalho; sem gastos, cobrança ou publicação. Meta do piloto: primeiro documento em até 5 min (ativação) e retorno em D7. Este backlog traduz isso no que o código precisa ter, ordenado por valor ÷ (risco × esforço).

Baseline (15/10/2026, branch `claude/blissful-pasteur-hvkev9`, ver README "Resultados verificados — Fase 0"):
- pytest 305 passed (273 da Fase 0 + 12 do item 1 + 8 do item 2 + 8 do item 4 + 4 do item 3);
- vitest 102 passed;
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
| 3 | Data por extenso — **feito**: "vinte e um de setembro de dois mil e vinte e seis" (dia 1 = "primeiro"). A forma "aos … dias do mês de …" fica para quando houver pedido real | M | B | P | — | — | Opção `date_format=words` no campo Data, com 4 vetores compartilhados (servidor e prévia iguais). |
| 4 | Listas prontas para qualificação das partes — **feito para estado civil e regime de bens**. Nacionalidade e profissão ficam fora: são listas abertas demais para uma lista fixa | M | B | P | — | — | Documento com "casada"/"comunhão parcial de bens" sugere Lista de opções completa, no gênero e na caixa do texto, um campo por parte ("Estado civil — Outorgante"). Tudo local, sem IA (`test_qualification_suggestion.py`). |
| 5 | Tipo de campo **OAB** — **feito** (opção A, migration 0005) | M | M (schema) | P | — | — | Aceita "OAB/ES 12.345", "ES 12345", "12.345/ES" e sufixos A/B/E; recusa UF inválida e número com mais de 6 dígitos; sai como "OAB/ES 12.345". Sugestão automática para "OAB/UF [nº] número". 8 vetores compartilhados; migration testada em PostgreSQL 17 (`test_oab.py`). |

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

### Item 4 — riscos e evidências
- **Gênero**: a lista segue o termo encontrado ("casada" → lista no feminino). Se o modelo for usado para uma pessoa de outro gênero, a lista precisa ser trocada à mão no campo. Isso fica registrado aqui, e o item 7 (condicionais) resolve depois.
- **Falso positivo**: palavras comuns como "separado do processo" e "casamento" não casam (testado); só "separado judicialmente" conta.
- **Cache**: `RULES_VERSION` passou de r3 para r4.
- **Evidência**: pytest 301 passed (+8). O fluxo upload → aceitar → gerar troca "casada" por "divorciada" no DOCX. E2E no Edge na `minuta-fase0` reconstruída: 16 passed. 4 deles caíram primeiro no limite de cadastro por hora (429) e passaram depois de zerar o contador só da stack de teste.

## Plano sem custo para o restante
| Ordem | Item | Pode começar já? | Bloqueio concreto |
|---|---|---|---|
| 1 | 3 Data por extenso | feito | — |
| 2 | 5 Campo OAB | feito (0005) | — |
| 3 | 9a Métricas de ativação | feito (D32, opt-in) | ligar no piloto: base legal + aviso aos participantes |
| 4 | 6 Biblioteca de modelos jurídicos | não | handoff de design (galeria) e revisão jurídica dos textos (custo: parecer profissional, adiado) |
| 5 | 7/8 Condicionais e partes repetíveis | não | Security review (mexe no parser/compilador DOCX) e design do editor |
| 6 | 9 Onboarding por perfil | não | design e Security review (toca o cadastro) |
| 7 | 10–15 cobrança, equipe, e-mail, LGPD, assinatura, OCR | não | Security review e decisões que geram custo (provedores pagos), adiadas por D29 |

## Próximo (precisam do handoff de design)

| # | Item | Valor | Risco | Esforço | Depende de | Gate | Critério de aceite |
|---|---|---|---|---|---|---|---|
| 6 | **Biblioteca de modelos jurídicos** (procuração ad judicia, contrato de honorários, substabelecimento, declaração de hipossuficiência) como "Experimentar com um exemplo" | A | B/M (textos precisam de revisão jurídica) | M | design (galeria), revisão jurídica | revisão de conteúdo | Cada modelo gera DOCX e PDF válidos, com campos e extenso. Avisa que é exemplo, não orientação jurídica. |
| 7 | **Cláusulas condicionais** (bloco que aparece por Sim/Não) | A | M (parser/compilador DOCX) | G | design do editor | Security review: muda o parser | Bloco marcado some ou aparece no DOCX e no PDF sem quebrar numeração nem estilos; testes de compilação para tabela, lista e cabeçalho. |
| 8 | **Partes repetíveis** (N outorgantes/réus) | A | M (parser) | G | 7 | Security review | Gera N blocos de qualificação; lote e kit continuam funcionando. |
| 9a | **Métricas de ativação agregadas** — **feito, opt-in (D32)**: contagens por dia/coorte derivadas das tabelas existentes, sem eventos nem IDs; ligar no piloto depende de base legal e aviso aos participantes | A (mede a meta do piloto) | M (dados de uso, LGPD) | M | — | revisão de segurança feita; base legal/aviso antes de ligar | Sem ID, horário exato, IP ou conteúdo; supressão < 5; sem FK; retenção 30 dias no rollup e no cleanup (`test_activation_metrics.py`). |
| 9 | Onboarding self-service orientado a escritório (perfil "advocacia" no cadastro) | M | M (toca cadastro) | M | design | Security review (auth) | Sem mudar o modelo de sessão ou permissões; só conteúdo inicial. |

## Depois (área sensível — só depois de Security review)

| # | Item | Valor | Risco | Esforço | Gate |
|---|---|---|---|---|---|
| 10 | Cobrança/planos (cota hoje é só limite técnico, `DEFAULT_LIMITS`) | A (negócio) | A | G | Security review + decisão de provedor (custo) |
| 11 | Convites e equipe no escritório (multi-usuário no mesmo workspace) | A | A (multitenancy/auth) | G | Security review |
| 12 | E-mail transacional real (hoje só recuperação de senha via SMTP opcional) | M | A (terceiro) | M | Security review + escolha de provedor |
| 13 | Retenção e LGPD para escritórios (sigilo profissional: prazo configurável, **exportação e exclusão do workspace sob demanda**, registro de acesso) — pré-requisito do piloto com documentos reais | A | A | M | Security review |
| 14 | Assinatura eletrônica | M | A (terceiro) | G | Security review + custo |
| 15 | OCR para PDF digitalizado (hoje recusado de propósito, D28) | M | A (uploads/parser) | G | Security review |
| 16 | **Content-Security-Policy completa com nonces** (hoje só `media-src 'self'`). Escopo: `script-src` com nonce por requisição via middleware do Next (sem `'unsafe-inline'`), `style-src`, `img-src 'self' data: blob:`, `connect-src 'self'`, `frame-ancestors 'none'`, `base-uri 'self'`, `form-action 'self'`, `object-src 'none'`; rodar antes em `Content-Security-Policy-Report-Only` e cobrir com E2E (editor, prévia, downloads, lote) — **pré-requisito do piloto** | A | A (todas as páginas) | M | Security review |

## Pendências conhecidas da baseline
- Não reexecutados nesta fase: pytest contra PostgreSQL real, lote de 1.000 e `scripts/crash_recovery_test.py`.
- O cadastro tem limite de 10 por hora por IP, e a suíte E2E cria cerca de 7 contas por execução (README).
