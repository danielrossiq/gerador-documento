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
| Usuários e sessões | banco | a conta continua existindo depois de `purge-workspace` (a eliminação é do workspace); sessões expiram (`SESSION_TTL_HOURS`) | exclusão de conta não tem comando hoje (pendência) |
| Logs da aplicação | saída padrão (JSON) → coletor da infraestrutura | definido pela infraestrutura | **política**: até 30 dias. Os logs não levam conteúdo de documento nem valores (filtro de máscara + código), mas levam IDs e IP |
| Backups do PostgreSQL e do MinIO | infraestrutura | **não existem no repositório** | **política**: até 35 dias, criptografados. Um workspace eliminado só some dos backups quando eles expiram; registrar a data da eliminação para não restaurá-lo |

Pendências (registradas, não resolvidas aqui):
- Prazo próprio para `template_files` e `generation_items.values`. Hoje só saem com `purge-workspace`.
- Exclusão de conta de usuário.
- Exportação e eliminação pela interface (hoje só pela linha de comando).

## 2. Exportação (portabilidade)

`python -m app.cli export-workspace <workspace_id> saida.json` gera **um JSON**.

**Contém** (todas as colunas das tabelas, como texto):
- modelos, versões, campos e auditoria;
- jobs e itens de geração — **inclui os valores preenchidos** (`generation_items.values`, dados pessoais);
- arquivos gerados: só os metadados e a chave no storage (`storage_key`).

**Não contém:**
- arquivos binários: nem o `.docx`/PDF enviado, nem o compilado, nem os documentos gerados;
- texto/estrutura do modelo (`template_blocks`), sugestões, kits e execuções de kit, importações de planilha;
- usuários, membros e sessões.

Teste: `tests/test_privacy_cli.py::test_export_has_metadata_and_values_but_no_file_contents`.

O arquivo de saída contém dados pessoais: entregue por canal seguro e apague a cópia local depois.

## 3. Eliminação (`purge-workspace`)

`python -m app.cli purge-workspace <workspace_id> --yes` roda em duas fases (`app/modules/privacy.py`):

1. Marca o workspace como **eliminação pendente** (`workspaces.deleted_at`). A partir daí ninguém acessa (a API responde 401).
2. Apaga do storage todos os arquivos do workspace (`template_files` e `generated_files`).
3. **Só se o storage confirmar todas as remoções**, apaga os registros do banco (DELETE do workspace com cascata).

Se alguma remoção falhar, o comando sai com **código 1** e "ELIMINAÇÃO PENDENTE". Os registros ficam, porque guardam as chaves dos arquivos que faltam apagar, e o acesso continua bloqueado. **Rode o mesmo comando de novo**: ele é idempotente e remover de novo uma chave já apagada não é erro.

Códigos de saída:
- 0: eliminado, ou workspace inexistente;
- 1: pendente;
- 2: faltou `--yes`.

Testes: `tests/test_privacy_cli.py`. Também verificado em PostgreSQL na stack `minuta-fase0`: o workspace e os `template_files` dele foram a zero.

## 4. Runbook

**Cleanup diário** (obrigatório):
- Agendar `python -m app.cli cleanup` a cada hora ou uma vez por dia (cron, CronJob ou Agendador de Tarefas).
- **Alertar quando a saída for diferente de 0**: algum arquivo expirado não saiu do storage.
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
