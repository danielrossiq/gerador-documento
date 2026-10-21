# Baseline do conjunto ouro (regras + heurísticas locais, sem IA)

Gerado por `python -m app.cli ai-eval baseline`. 15 modelos fictícios (app/eval/gold.py).

| Métrica | Valor | Meta do F1 |
|---|---:|---:|
| Recall de ocorrências (trecho exato) | 53.5% | ≥ 90% |
| Precisão | 78.6% | ≥ 90% |
| Recall de campos | 52.7% | — |
| Tipo correto (entre acertos) | 98.9% | — |
| Agrupamento de ocorrências | 75.0% | — |
| Ocorrências só parcialmente cobertas | 12.8% | — |

## Recall de campos por tipo

| Tipo | Recall |
|---|---:|
| cep | 100.0% |
| cnpj | 100.0% |
| cpf | 100.0% |
| currency | 92.3% |
| date | 100.0% |
| email | 100.0% |
| number | 0.0% |
| oab | 100.0% |
| phone | 100.0% |
| select | 42.9% |
| text_long | 0.0% |
| text_short | 17.9% |

## Por documento

| Documento | Categoria | Recall ocorr. | Precisão | Campos achados | Não achados |
|---|---|---:|---:|---:|---|
| servicos-ti | serviços | 66.7% | 83.3% | 8/13 | cidade, dia_pagamento, endereco_contratante, prazo_meses, servico |
| servicos-limpeza | serviços | 58.3% | 70.0% | 7/12 | cidade, dia_semana, endereco_imovel, nome_contratado, nome_contratante |
| locacao-residencial | locação | 58.8% | 90.9% | 10/17 | cidade, endereco_imovel, garantia, indice_reajuste, nacionalidade_locador, nacionalidade_locataria, prazo_meses |
| locacao-comercial | locação | 53.8% | 87.5% | 7/13 | cidade, dia_vencimento, endereco_imovel, finalidade, prazo_meses, representante |
| procuracao-ad-judicia | procuração | 53.8% | 77.8% | 6/12 | acao, cidade, endereco_escritorio, nacionalidade, parte_contraria, profissao |
| substabelecimento | procuração | 37.5% | 75.0% | 3/8 | cidade, nome_cliente, nome_substabelecente, nome_substabelecido, numero_processo |
| declaracao-hipossuficiencia | declaração | 88.9% | 100.0% | 7/8 | cidade |
| declaracao-residencia | declaração | 45.5% | 83.3% | 5/10 | bairro, cidade, endereco, nome_declarante, nome_morador |
| recibo-honorarios | recibo | 36.4% | 80.0% | 4/11 | cidade, forma_pagamento, nome_pagador, nome_recebedor, referencia, valor, valor_extenso |
| recibo-aluguel | recibo | 37.5% | 50.0% | 3/8 | cidade, endereco_imovel, mes_referencia, nome_locador, nome_locatario |
| termo-confidencialidade | termo | 45.5% | 83.3% | 5/11 | cidade, foro, nome_empresa, nome_parceiro, prazo_anos, projeto |
| termo-acordo | termo | 54.5% | 75.0% | 6/11 | cidade, multa_percentual, nome_credor, nome_devedor, parcelas |
| proposta-honorarios | proposta | 45.5% | 71.4% | 5/11 | contato_cliente, nome_advogado, nome_cliente, nome_escritorio, percentual_exito, servico_juridico |
| rh-contrato-trabalho | RH | 58.3% | 77.8% | 7/12 | cidade, endereco_empregada, experiencia_dias, jornada_horas, nome_empregadora |
| rh-aviso-ferias | RH | 50.0% | 62.5% | 5/10 | cidade, matricula, nome_empregado, nome_empresa, periodo_aquisitivo |
