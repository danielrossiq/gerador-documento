# Evidências da Fase 2 — matriz de aceite do design

Resposta de Dev à "Matriz objetiva de evidências para Dev" de `design/fase2-minuta-especificacao.md`.

**Coleta:** `EVIDENCE=1 npx playwright test e2e/evidence.spec.ts`. Para cada rota × viewport, o teste:
- tira uma captura full-page;
- mede a largura de rolagem da página contra a largura útil;
- roda o axe com as tags WCAG 2.0, 2.1 e 2.2 A/AA.

O resultado vai para `resultados.json`. As capturas (PNG, cerca de 6 MB) não são versionadas; ficam em `Shared/DanielRossi/docs/design/evidencias-fase2/` e podem ser regeradas com o mesmo comando.

**Ambiente:**
- Stack Docker `minuta-fase0` (PostgreSQL 17, Redis, MinIO, API, worker e web), com as travas do piloto `PDF_IMPORT_ENABLED=false` e `EXTERNAL_AI_ENABLED=false`.
- Microsoft Edge 155.0.4283.45 via Playwright 1.63.0; axe-core 4.13.0.
- Conta de demonstração com dados fictícios. Zoom 100%.

## Resultado (16/10/2026)

| Viewport | Rotas/estados | Rolagem horizontal da página | Violações axe (WCAG 2.2 A/AA) |
|---|---|---|---|
| 1440×900 | 23 | 0 | 0 |
| 1024×768 | 23 | 0 | 0 |
| 390×844 | 23 | 0 | 0 |
| 320×720 | 23 | 0 | 0 |

Rotas e estados cobertos:
- **Sem sessão:** A1 login (inicial e erro de campo), A2 cadastro, A3 esqueci a senha, A4 redefinir (sem token e com token).
- **Com sessão:**
  - M1 início e M1b modelos;
  - M2 novo modelo e M2b etapa Documento;
  - M3 editor e M3b revisão;
  - M4 preencher (inicial e com erros);
  - M5 lote;
  - M6 kits, M7 novo kit, M8 editar kit e M9 usar kit (formulário e erros ao gerar vazio; kit de exemplo criado pela coleta, se a conta não tiver);
  - M10 histórico;
  - M11 detalhe do histórico (sucesso e parcial).

## Defeitos encontrados e corrigidos nesta coleta

Coleta refeita no commit do tipo OAB (6fecfde). A primeira rodada encontrou 12 casos de rolagem horizontal e uma violação WCAG 2.2:

| Defeito | Onde | Correção |
|---|---|---|
| Página com 1172 px de largura | M5 lote em 390 e 320 px | coluna da grade `minmax(0,1fr)` (a lista de erros forçava a largura) |
| Página com 658 px | M11 detalhe do histórico em 390 e 320 px | coluna `minmax(0,1fr)` e `min-w-0` (a tabela tem rolagem própria) |
| +4 a +11 px | barra de etapas e abas "Um documento / Vários documentos" em 320 px (M2, M2b, M3b, M4, M5) | abaixo de 400 px, só a etapa atual mostra o nome (as outras têm nome para leitor de tela); o ícone das abas some |
| +17 px | M7 novo kit em 320 px | `fieldset` com `min-w-0` e lista com coluna `minmax(0,1fr)` |
| `target-size` (WCAG 2.2 2.5.8) | links da lista de erros do formulário (M4) | alvo com no mínimo 24 px de altura |
| Campo com foco atrás da barra fixa de ações (WCAG 2.2 2.4.11) | M4 em 320 px | `scroll-padding-bottom` quando a página tem barra fixa; teste em `mobile.spec.ts` falha antes da correção e passa depois |

## Lacunas desta coleta

- **Sem dados para o estado:**
  - M11 com falha: não há job falho na stack de teste;
  - resultado da execução de um kit (o E2E `kits.spec.ts` gera e baixa o ZIP, mas sem captura nos 4 viewports).
- **Estados sem captura:** carregando, sessão expirada e A0 (redirecionamento).
- **Não automatizável aqui:** teclado virtual real, zoom de 200%, leitor de tela e verificação manual de contraste em hover/disabled. O axe confere contraste só do estado renderizado. Esta coleta **não** declara conformidade WCAG.
