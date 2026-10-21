# Avaliação de modelos de IA no conjunto ouro

Gerado por `python -m app.cli ai-eval models`. 15 documentos fictícios (app/eval/gold.py); cada modelo roda junto com as regras determinísticas, como na análise real. Custo = informado pela OpenRouter.

| Modelo | Recall ocorr. | Precisão | Recall campos | Tipo | Agrupamento | Custo/doc (US$) | Tempo/doc | Falhas |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| regras + heurísticas locais (sem IA) | 53.5% | 78.6% | 52.7% | 98.9% | 75.0% | 0 | — | — |
| `google/gemini-2.5-flash-lite` | 84.3% | 90.1% | 85.6% | 95.9% | 25.0% | 0.00045 | 2.9 s | 0 |
| `openai/gpt-5.6-luna` | 91.3% | 92.4% | 91.0% | 95.5% | 100.0% | 0.00112 | 7.0 s | 0 |
| `anthropic/claude-haiku-5.5` | 91.9% | 94.0% | 92.2% | 96.8% | 75.0% | 0.00091 | 6.8 s | 0 |
| `openai/gpt-5-nano` | 43.6% | 89.3% | 44.9% | 98.7% | 0.0% | 0.00165 | 37.6 s | 15 |
| `deepseek/deepseek-v4.1-flash` | 70.3% | 91.7% | 70.7% | 98.3% | 50.0% | 0.00153 | 9.7 s | 3 |
| `mistralai/mistral-small-2603` | 64.0% | 89.4% | 64.1% | 98.2% | 50.0% | 0.00133 | 13.2 s | 6 |
| `anthropic/claude-sonnet-5` | 91.9% | 93.5% | 92.2% | 95.6% | 75.0% | 0.01300 | 8.2 s | 0 |
