# Roadmap

## MVP (entregue)
- Cadastro/login/recuperação, workspaces isolados (papéis `owner`/`member`).
- Painel, CRUD de geradores (duplicar, arquivar, excluir com confirmação), busca e filtros.
- Upload `.docx` seguro → editor visual (TipTap) com **selecionar → Transformar em campo**, inserir no cursor, reutilizar campo, destacar ocorrências, buscar, desfazer/refazer, autosave com indicador e aviso ao sair, histórico de versões.
- 13 tipos de campo com validação/máscara pt-BR (CPF/CNPJ incl. alfanumérico, CEP, telefone, moeda, data…), lista suspensa completa.
- Sugestões: regras determinísticas + IA opcional (ou heurísticas locais explícitas), cache por hash, revisão aceitar/editar/ignorar.
- Formulário individual com prévia ao vivo → DOCX e PDF reais.
- Lote estilo planilha (grade virtualizada, colar do Excel, preencher para baixo, filtros, painel de erros, importação XLSX/CSV com mapeamento, planilha-modelo), job assíncrono, progresso, ZIP + relatório CSV.
- Histórico, links de download assinados/expiráveis, repetição de geração, auditoria, métricas, retenção.
- **Kit de documentos**: agrupar geradores existentes que compartilham variáveis num formulário só; mapeamento manual ou detecção automática por rótulo; geração de todos os documentos do kit de uma vez, com download individual, ZIP consolidado e relatório CSV.
- Docker Compose completo (Postgres, Redis, MinIO, API, worker+LibreOffice, web), migrations, seed.
- **Revisão de UX** ([D27](DECISIONS.md)): etapas Modelo → Campos → Revisão → Gerar em todas as telas do gerador; etapa Modelo para enviar/trocar o .docx; revisão com pendências e prévia com dados de exemplo; avisos de nome repetido/lista sem opções/campo fora do documento; ordem do formulário igual à do documento; rascunho automático do formulário; "preencher com exemplo"; resumo antes de gerar vários; menu e telas sem rolagem horizontal no celular.

## Próxima versão
0. **Continuações da revisão de UX** (dependem de backend ou de decisão de produto):
   - rascunho do formulário/planilha **no servidor**, para continuar em outro dispositivo — exige decidir retenção e LGPD de dados pessoais ainda não gerados;
   - "desfazer" ao excluir um campo (hoje há confirmação e o texto original pode ser mantido);
   - pendências como bloqueio opcional no servidor (hoje são avisos);
   - prévia fiel (item 6).
1. **Convites e gestão de equipe** (UI para `owner`/`member`, troca de workspace, auditoria consultável).
2. **Edição estrutural de tabelas** (linhas/colunas) e listas numeradas; fidelidade de alterações rastreadas (`w:ins/w:del`).
3. **Campos condicionais e repetíveis** (blocos que aparecem por Sim/Não; tabelas com N linhas), valor por extenso (moeda/data).
4. **Assinatura eletrônica** (fluxo com provedor; hoje há só ponto de extensão no modelo de jobs).
5. **Entrada PDF (beta)**: fundo + campos posicionados (interface `TemplateSourceParser` já prevista).
6. **Prévia fiel**: renderizar o DOCX compilado (LibreOffice → PDF/PNG) ao lado do formulário em vez da aproximação HTML.
7. **Download direto por URL pré-assinada do S3** (arquivos grandes) e upload por URL assinada.
8. Login social (Google/Microsoft), 2FA, antivírus de upload, CSP com nonce.
9. Reanálise incremental por bloco e feedback do usuário para melhorar sugestões.

## Escala futura
- Extrair `worker`/`generation` para serviço próprio quando a carga justificar (fronteira já isolada por fila e adaptadores).
- Particionar `generation_items`/`generated_files`/`audit_events` por data; arquivamento em storage frio.
- Filas separadas por prioridade (individual > lote) e autoscaling de workers por profundidade de fila.
- Pool de instâncias LibreOffice residentes (unoserver) para reduzir o custo de partida em cargas muito altas.
- Cotas e faturamento por workspace; cache de gabaritos compilados por versão; CDN para downloads.
- Multi-região/DR: réplicas de leitura, storage com replicação, `SECRET_KEY` por região.
- Observabilidade completa (OpenTelemetry: traces API→fila→worker).
