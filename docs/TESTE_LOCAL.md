# Teste local — stack `minuta-fase0`

Stack Docker separada da stack `minuta` original. Volumes próprios; a stack `minuta` e os volumes dela não são tocados.

## Endereços

| O quê | Onde |
|---|---|
| Aplicação | http://localhost:3210 (landing pública em `/`; ver `docs/SITE.md`) |
| API (OpenAPI) | http://localhost:8110/api/docs · saúde: http://localhost:8110/health e /ready |
| Console do MinIO | http://localhost:9111 (usuário e senha: `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` do `.env`) |
| Login de demonstração | `demo@minuta.app` / `demo12345` (dados fictícios, criados pelo seed) |

Travas do piloto ativas: `PDF_IMPORT_ENABLED=false` (só Word) e `EXTERNAL_AI_ENABLED=false` (nenhuma IA externa).

## Serviços pagos e substitutos locais (sem custo, sem chamada real)

| Serviço real (pago/terceiro) | No teste local | Interface para trocar depois |
|---|---|---|
| Gateway de pagamento / cobrança | **não existe no código**: cobrança é o item 10 do backlog, bloqueado por Security review e custo (D29). Nenhuma tela ou fluxo depende dele; os planos são só limites técnicos (`DEFAULT_LIMITS`). Por isso não há mock | — (entra como adapter novo quando for decidido) |
| E-mail transacional | `ConsoleNotifier`: o link de recuperação de senha aparece no log da API (só fora de produção) | `adapters/notify.py` (`Notifier`; `SmtpNotifier` com `SMTP_*`) |
| IA externa (Anthropic, TypeSafe) | provedor local de heurísticas; trava `EXTERNAL_AI_ENABLED=false` | `adapters/ai/` (`get_ai_provider`, `get_role_classifier`) |
| Armazenamento S3 | MinIO local (contêiner da própria stack) | `adapters/storage.py` (`StorageAdapter`) |
| Conversão para PDF | LibreOffice no contêiner do worker (gratuito) | `adapters/pdf.py` |

## Checklist de inicialização (manhã)

1. Abrir o Docker Desktop e esperar "Engine running".
2. `docker compose -p minuta-fase0 ps` (com as portas exportadas): api e postgres devem estar `healthy`. Se estiverem parados, `… up -d`, **sem** `--build` se o código não mudou.
3. Só se houver commits novos desde a última subida, depois da revisão: `… up -d --build`. O serviço `migrate` aplica as migrations; o seed não duplica dados.
4. `curl http://localhost:8110/health` deve devolver `{"status":"ok"}`, e `/ready` deve devolver `database` e `pdf_converter` ok.
5. Abrir http://localhost:3210 e entrar com `demo@minuta.app` / `demo12345`.
6. Seguir o roteiro abaixo. Usar só dados fictícios: este não é o piloto com dados reais.
7. Ao terminar: `docker compose -p minuta-fase0 stop`. Nunca `down -v`. A stack `minuta` não deve ser usada nem alterada.

## Subir, parar e reconstruir

Rodar na raiz do repositório (Git Bash):

```bash
export WEB_PORT=3210 API_PORT=8110 MINIO_CONSOLE_PORT=9111   # PowerShell: $env:WEB_PORT="3210"; …
docker compose -p minuta-fase0 up -d --build    # aplica migrations (até 0006) e o seed, sem apagar dados
docker compose -p minuta-fase0 ps
docker compose -p minuta-fase0 stop             # parar (mantém dados)
```

A porta 3100 está ocupada por outro projeto nesta máquina; por isso o web usa 3210. **Não** use `down -v`: isso apaga os volumes.

## Roteiro curto

1. Entrar com a conta de demonstração.
2. **Início:**
   - colar uma tabela com títulos ("Nome do contratante", "CPF do contratante"…) em "Gerar em lote colando uma planilha";
   - colar a mesma tabela sem títulos: aparece o aviso "A primeira linha parece ser dado".
3. **Novo modelo:** enviar um `.docx` com "R$ 5.000,00 (cinco mil reais)", "casada", "comunhão parcial de bens" e "OAB/ES 12.345". Nas sugestões, conferir:
   - Valor com extenso;
   - Estado civil e Regime de bens com listas prontas;
   - OAB.
4. **Campo Data:** escolher "por extenso"; a prévia mostra "vinte e um de setembro de…".
5. **PDF:** enviar um PDF. Ele é recusado com a explicação, porque o PDF está desligado no piloto.
6. **Celular:** abrir em 390 px e em 320 px (DevTools). Nenhuma tela deve ter rolagem horizontal.

## Testes automatizados

```bash
cd frontend
E2E_BASE_URL=http://localhost:3210 E2E_CHANNEL=msedge npx playwright test        # 18 passam, 7 sob demanda
EVIDENCE=1 E2E_BASE_URL=http://localhost:3210 E2E_CHANNEL=msedge npx playwright test e2e/evidence.spec.ts
```

O cadastro tem limite de 10 por hora por IP. Se a suíte cair com "Muitas tentativas", zere o contador **só desta stack**:

```bash
docker exec minuta-fase0-redis-1 sh -c 'for k in $(redis-cli --scan --pattern "rl:register:*"); do redis-cli del $k; done'
```

## Administração (LGPD)

```bash
docker exec minuta-fase0-api-1 python -m app.cli cleanup                              # sai com 1 se sobrar pendente
docker exec minuta-fase0-api-1 python -m app.cli metrics-rollup                       # agregados de ativação (só com ACTIVATION_METRICS_ENABLED=true)
docker exec minuta-fase0-api-1 python -m app.cli metrics-report
docker exec minuta-fase0-api-1 python -m app.cli export-workspace <id> /tmp/x.json --files /tmp/arquivos
docker exec minuta-fase0-api-1 python -m app.cli purge-workspace <id> --yes           # IRREVERSÍVEL
```

Use `purge-workspace` só em workspace de teste. Política e runbook: [RETENCAO_E_ELIMINACAO.md](RETENCAO_E_ELIMINACAO.md).
