# Teste local — stack `minuta-fase0`

Stack Docker separada da stack `minuta` original. Volumes próprios; a stack `minuta` e os volumes dela não são tocados.

## Endereços

| O quê | Onde |
|---|---|
| Aplicação | http://localhost:3210 |
| API (OpenAPI) | http://localhost:8110/api/docs · saúde: http://localhost:8110/health e /ready |
| Console do MinIO | http://localhost:9111 (usuário e senha: `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` do `.env`) |
| Login de demonstração | `demo@minuta.app` / `demo12345` (dados fictícios, criados pelo seed) |

Travas do piloto ativas: `PDF_IMPORT_ENABLED=false` (só Word) e `EXTERNAL_AI_ENABLED=false` (nenhuma IA externa).

## Subir, parar e reconstruir

Rodar na raiz do repositório (Git Bash):

```bash
export WEB_PORT=3210 API_PORT=8110 MINIO_CONSOLE_PORT=9111   # PowerShell: $env:WEB_PORT="3210"; …
docker compose -p minuta-fase0 up -d --build    # aplica migrations (até 0005) e o seed, sem apagar dados
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
docker exec minuta-fase0-api-1 python -m app.cli export-workspace <id> /tmp/x.json --files /tmp/arquivos
docker exec minuta-fase0-api-1 python -m app.cli purge-workspace <id> --yes           # IRREVERSÍVEL
```

Use `purge-workspace` só em workspace de teste. Política e runbook: [RETENCAO_E_ELIMINACAO.md](RETENCAO_E_ELIMINACAO.md).
