# Retenção, exportação e eliminação — política e runbook

> Política **operacional** para o piloto. Descreve o que o código faz hoje e o que a operação precisa fazer à mão. Não é parecer jurídico; os prazos precisam de validação profissional antes de um piloto com documentos reais (D29).

## 1. O que guardamos, onde e por quanto tempo

| Dado | Onde | Prazo hoje | Como sai |
|---|---|---|---|
| Documentos gerados (DOCX/PDF, ZIP e CSV de lote) — `generated_files` | storage (S3/MinIO) + metadados no banco | **`FILE_RETENTION_DAYS`** (padrão 7 dias) | `python -m app.cli cleanup` apaga do storage e marca o registro; o registro é apagado 30 dias depois. Links recusam arquivo expirado (410). |
| Modelo enviado e modelo compilado — `template_files` (original `.docx`, ou `.docx` convertido de PDF, e o compilado) | storage + banco | **enquanto o workspace existir**, inclusive versões antigas e modelos excluídos (exclusão de modelo é *soft delete*) | só por `purge-workspace` |
| Valores preenchidos — `generation_items.values` | banco | **enquanto o workspace existir**; o arquivo expira, os valores não | só por `purge-workspace` |
| Estrutura e texto do modelo (blocos, campos, sugestões) | banco | enquanto o workspace existir | `purge-workspace` |
| Auditoria — `audit_events` | banco | enquanto o workspace existir; não guarda valores, conteúdo, CPF nem e-mail | `purge-workspace` |
| Usuários e sessões | banco | enquanto a pessoa for membro de algum workspace; sessões expiram (`SESSION_TTL_HOURS`) | `purge-workspace` apaga as contas que ficam **sem nenhum workspace** (com sessões, tokens de recuperação e identidades). Quem é membro de outro workspace continua |
| Logs da aplicação | saída padrão (JSON) → coletor da infraestrutura | definido pela infraestrutura | **política**: até 30 dias. Os logs não levam conteúdo de documento nem valores: o código não os passa, um filtro mascara CPF/CNPJ/e-mail/telefone e exceções são registradas **sem a mensagem**, só com tipo e linha do código (`safe_exception_text`). Levam IDs e IP |
| Backups do PostgreSQL e do MinIO | infraestrutura | **não existem no repositório** | **política**: até 35 dias, criptografados. Um workspace eliminado só some dos backups quando eles expiram; registrar a data da eliminação para não restaurá-lo |

Pendências (registradas, não resolvidas aqui):
- Prazo próprio para `template_files` e `generation_items.values`. Hoje só saem com `purge-workspace`.
- Exclusão de conta isolada, sem eliminar o workspace (hoje a conta só sai junto com o último workspace dela).
- Exportação e eliminação pela interface (hoje só pela linha de comando).

## 2. Exportação (portabilidade)

`python -m app.cli export-workspace <workspace_id> saida.json [--files PASTA]` gera um JSON (`formato: minuta-export-v2`).

**Contém:**
- **todas** as tabelas com `workspace_id`: modelos, versões, blocos/texto do modelo, campos, opções, ocorrências, sugestões, arquivos enviados e gerados (metadados), jobs, itens (**com os valores preenchidos**), importações de planilha, kits, execuções de kit, análises e auditoria;
- os dados da conta de cada membro (id, nome, e-mail, ativo, datas) e o provedor de login.

**Com `--files PASTA`:** copia também os binários do storage (modelo enviado, compilado e documentos gerados ainda não expirados). Cada registro ganha `arquivo_exportado`, ou `falha_exportacao` com o tipo do erro. Arquivo expirado ou com falha não interrompe a exportação, mas o comando sai com 1.

**Nunca contém:** sessões de login, `password_hash`, `token_hash`, `csrf_token` e chaves de idempotência.

Testes: `tests/test_privacy_cli.py::test_export_covers_every_workspace_table_without_secrets` e `::test_export_with_files_copies_the_binaries`.

O arquivo de saída contém dados pessoais: entregue por canal seguro e apague a cópia local depois.

## 3. Eliminação (`purge-workspace`)

`python -m app.cli purge-workspace <workspace_id> --yes` roda em duas fases (`app/modules/privacy.py`):

1. Marca o workspace como **eliminação pendente** (`workspaces.deleted_at`). A partir daí ninguém acessa (a API responde 401).
2. Apaga do storage todos os arquivos do workspace (`template_files` e `generated_files`).
3. **Só se o storage confirmar todas as remoções**, apaga os registros do banco (DELETE do workspace com cascata) e, **na mesma transação**, as contas que ficaram sem nenhum workspace.

Se alguma remoção falhar, o comando sai com **código 1** e "ELIMINAÇÃO PENDENTE". Os registros ficam, porque guardam as chaves dos arquivos que faltam apagar, e o acesso continua bloqueado. **Rode o mesmo comando de novo**: ele é idempotente e remover de novo uma chave já apagada não é erro.

Códigos de saída:
- 0: eliminado, ou workspace inexistente;
- 1: pendente;
- 2: faltou `--yes`.

Testes: `tests/test_privacy_cli.py`. Também verificado em PostgreSQL na stack `minuta-fase0`: o workspace e os `template_files` dele foram a zero.

## 4. Runbook

**Cleanup diário** (obrigatório):
- Agendar `python -m app.cli cleanup` a cada hora ou uma vez por dia (cron, CronJob ou Agendador de Tarefas). Cada execução repete lotes de 500 até não sobrar arquivo expirado, ou até só sobrarem os que falharam.
- **Alertar quando a saída for diferente de 0**: algum arquivo expirado não saiu do storage, ou ainda há pendentes.
- Acompanhar o evento de log `cleanup_concluido` (`removidos`, `falhas`, `pendentes`). Se `pendentes` crescer entre rodadas, o cleanup não está dando conta; rode de novo ou aumente a frequência.

**Pedido de eliminação de um titular/cliente:**
1. Identificar o workspace.
2. Exportar, se pedido (seção 2).
3. Rodar `purge-workspace`.
4. Se sair com 1: verificar o storage e repetir até sair com 0.
5. Registrar data/hora e o ID do workspace no controle de pedidos. Os backups expiram no prazo da seção 1; não restaurar esse workspace de um backup.

**Antes do piloto:**
- confirmar os prazos com revisão profissional;
- ligar o cleanup agendado com alerta;
- definir a retenção do coletor de logs e dos backups;
- manter `PDF_IMPORT_ENABLED=false` e `EXTERNAL_AI_ENABLED=false` (D30).

## 5. Evidência de retenção (testes automatizados)

| O que prova | Teste |
|---|---|
| arquivos gerados expirados saem do storage e do link, em vários lotes, até zerar | `test_privacy_cli.py::test_cleanup_removes_every_expired_file_in_batches` |
| falha no storage deixa pendentes, avisa e sai com 1 | `::test_cleanup_with_storage_failure_reports_pending_and_exits_1` e `::test_cleanup_exit_code_reports_failures` |
| eliminação não apaga o banco se o storage falhar; nova tentativa conclui | `::test_purge_keeps_records_when_storage_fails_and_finishes_on_retry` |
| contas sem outro workspace saem na eliminação; as compartilhadas ficam | `::test_purge_removes_accounts_left_without_workspace_but_keeps_shared_ones` |
| logs sem mensagem de exceção (inclusive o erro da conversão de PDF) | `test_log_sanitization.py` |

Os testes de eliminação usam workspaces descartáveis criados no próprio teste: nunca dados existentes.
