# Plano de repaginação — Minuta

Base: `claude/blissful-pasteur-hvkev9`, commit `6d2d8b5`. Data: 17/10/2026.

## Princípios
- Preservar rotas, dados, geração e contratos existentes; pt-BR, acessibilidade, responsividade e temas claro/escuro.
- Nenhuma chamada de IA paga em desenvolvimento, testes ou CI. `AI_ENABLED=false`; demo offline identificada. Billing `none`, sem checkout.
- Nunca publicar na main, nunca comitar segredos, sem AGPL. Mudanças de banco, se necessárias, reversíveis.
- Números, preços e depoimentos ilustrativos em uma única fonte explicitamente fictícia.

## Fases e responsáveis
1. **Leitura e baseline (Chief):** README e docs, conferir base, criar esta branch e plano, instalar ferramentas e registrar testes existentes.
2. **Design e frontend (Bot 2, worktree/branch própria):** sistema visual premium, landing pública e redirecionamento autenticado, login/cadastro, shell e telas internas, tema claro/escuro, responsividade, estados e acessibilidade. Centralizar conteúdo ilustrativo; galeria oculta de criativos. Sem tocar backend.
3. **Código IA, planos e segurança (Bot 3, worktree/branch própria):** gateway único com demo offline e tetos, recursos assistidos (modelo, extração, revisão, comando e limpeza de lote), endpoints autenticados, billing none/uso, testes bloqueando rede de IA, documentação de ativação e revisão de segurança. Preservar provedores/regras atuais.
4. **Identidade, infraestrutura e QA (Chief):** assets sem pessoas/marcas externas, integrar frontend/backend; execução via Compose conforme README; testes backend/frontend/E2E e revisão adversarial. Sol/OpenAI somente se houver recurso gratuito disponível: nenhuma geração paga é autorizada. Se indisponível, registrar limitação e entregar assets vetoriais locais sem custo.
5. **Integração e entrega (Chief):** cherry-pick dos commits dos bots, correções de regressões, prints reais, roteiro curto, lista do fictício e instruções de ativação, commit e push exclusivamente da branch de entrega.

## Isolamento e contrato entre frentes
- Chief: `feat/minuta-saas-repaginacao`, repositório de integração.
- Bot 2: `feat/minuta-saas-ui`, worktree separado. Responsável por frontend e assets visuais.
- Bot 3: `feat/minuta-saas-ai`, worktree separado. Responsável por backend, `.env.example` e docs/IA_ATIVACAO.md.
- Bots leem README e docs antes de editar; não fazem push ou merge na main. Chief integra commits e resolve contratos.
- Integração sugerida: `/api/assistant/*` e `/api/billing/*`, schemas documentados pelo Bot 3 ao Bot 2; telas sempre mostram modo Demonstração.

## Gates de entrega
- Testes backend verdes; typecheck/lint/build frontend e E2E quando infraestrutura permitir.
- Teste de proteção impede rede de IA em modo desligado/demo; chaves vazias nos exemplos.
- Sem checkout, preço leva ao cadastro; placeholders visíveis como ilustração, não prova social real.
- Verificar isolamento de workspace, limites e ausência de dados sensíveis em logs; rotas legadas preservadas.
- Registrar limitações verificadas, nunca declarar teste ou geração de imagem não executados.
