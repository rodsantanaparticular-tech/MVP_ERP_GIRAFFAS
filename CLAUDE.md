# CLAUDE.md — ERP IN-360 (MVP) · pasta MVP_ERP_GIRAFFAS

## Identidade do projeto
**Aqui nasce o MVP do ERP IN-360.** Novos módulos (ex.: Conciliação de Pagamentos 3 vias) são
construídos AQUI, não nas pastas de origem.

Sistema **unificado** (monólito modular, Docker Compose, Local-First agora, nuvem 24x7 depois) que junta dois projetos
existentes da franquia Giraffas, rumo a um produto multi-tenant para redes de franquias:
- **Datalake** (indicadores ABS, quebra de caixa, metas, desperdício/break, conciliação financeira), em
  `G:\Meu Drive\1-RSIN(holding)\3-Rodiza - Giraffas\Gestao\Giraffas-Datalake`
- **Raio-X do DRE / IN-360** (FastAPI + Postgres, auditoria de despesas do GCOM), em
  `C:\Users\rodsa\OneDrive\Documentos\GESTÃO_GIRAFFAS\in-360-giraffas`

Plano de referência: `docs/PLANO_ENGENHARIA.md`. Stack: FastAPI, SQLAlchemy/Alembic, PostgreSQL 16,
pandas, Playwright, n8n, Streamlit (console interno).

## Regras deste projeto
- **As duas pastas de origem são SOMENTE LEITURA.** Copiar código para cá, nunca mover nem editar lá.
  Elas continuam em produção até o corte de cada módulo (ver fases do plano).
- **Não alterar regra de negócio** ao portar pipelines. Toda portabilidade passa por teste de paridade
  contra o dataset de referência (`tests/paridade/`).
- **Dados vivos nunca no repositório** (este repo fica no OneDrive): Postgres em volume nomeado, o resto
  em `DATA_DIR` fora de OneDrive e Google Drive.
- **Segredos:** nunca em código, `.env` commitado, logs, STATUS.md ou chat. Credenciais de integração
  ficam no cofre (`credenciais`, cifragem envelope). Na transição, o keyring do Windows continua valendo.
- **Captcha:** só o provider `manual` (humano resolve). Não integrar nem sugerir serviços de resolução
  automática nem contornar captcha. Falta de humano gera o status `manual_action_required`.
- **Escrita no GCOM** exige sempre confirmação humana explícita.

## Protocolo obrigatório — alerta de cruzamento de projetos
Seguir o protocolo do CLAUDE.md global: se o pedido parecer de **outro** projeto (inclusive das duas
pastas de origem, quando for trabalho a ser feito *nelas*), parar, alertar e só prosseguir com
confirmação explícita. Não expor nome ou detalhes de projetos não relacionados.

## Convenção de acompanhamento
Manter `STATUS.md` na raiz atualizado ao fim de cada sessão ou marco. **Ler o STATUS.md antes de
retomar qualquer trabalho.**
