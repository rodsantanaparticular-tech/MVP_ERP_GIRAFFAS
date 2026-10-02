"""Passo 5c-3: conciliações banco × GCOM (match de cada saída do extrato com o documento que ela pagou)

Revision ID: d1e2f3a4b5c6
Revises: c9d0e1f2a3b4
Create Date: 2026-10-02

Parte 3 do modelo 002 (`database/sql/002_conciliacao_pagamentos.sql`). Diferenças em relação ao DDL de referência:
- `conciliacao_itens` tem `tenant_id` próprio, com RLS (o 002 dependia do acesso sempre pelo pai);
- `acrescimo`: multa/juros por pagamento em atraso (JM), separado da diferença;
- `despesa_id` é integer (a tabela `despesas` veio do Raio-X com id integer).
O ciclo de vida da previsão (`despesa_status_historico`, views) fica para quando as previsões do GCOM entrarem.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS = """
    ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;
    ALTER TABLE {t} FORCE ROW LEVEL SECURITY;
    CREATE POLICY isolamento_tenant ON {t}
      USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)
      WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint);
"""


def upgrade() -> None:
    op.execute("""
    CREATE TABLE conciliacoes (
        id              bigserial PRIMARY KEY,
        tenant_id       bigint NOT NULL REFERENCES tenants(id),
        competencia     char(7) NOT NULL,
        status          text NOT NULL CHECK (status IN ('batido','sugerido','pendente','investigar','descartado')),
        padrao_id       bigint REFERENCES padroes_pagamento(id),
        regra_aplicada  text NOT NULL,
        total_extrato   numeric(14,2) NOT NULL,
        total_despesas  numeric(14,2) NOT NULL,
        diferenca       numeric(14,2) GENERATED ALWAYS AS (total_extrato - total_despesas) STORED,
        acrescimo       numeric(14,2) NOT NULL DEFAULT 0,
        nota            text,
        criado_por      text NOT NULL,             -- 'motor' | 'usuario:<id>'
        criado_em       timestamptz NOT NULL DEFAULT now(),
        confirmado_por  integer REFERENCES usuarios(id),
        confirmado_em   timestamptz);
    CREATE INDEX ix_conciliacoes_comp ON conciliacoes (tenant_id, competencia, status);

    CREATE TABLE conciliacao_itens (
        id                     bigserial PRIMARY KEY,
        tenant_id              bigint NOT NULL REFERENCES tenants(id),
        conciliacao_id         bigint NOT NULL REFERENCES conciliacoes(id) ON DELETE CASCADE,
        tipo                   text NOT NULL CHECK (tipo IN ('previsao','despesa','extrato')),
        extrato_lancamento_id  bigint REFERENCES extrato_lancamentos(id),
        despesa_id             integer REFERENCES despesas(id),
        valor_alocado          numeric(14,2) NOT NULL,
        ativo                  boolean NOT NULL DEFAULT true,
        CHECK ((tipo = 'extrato' AND extrato_lancamento_id IS NOT NULL AND despesa_id IS NULL) OR
               (tipo IN ('previsao','despesa') AND despesa_id IS NOT NULL AND extrato_lancamento_id IS NULL)));
    -- um débito do extrato só pode estar em UMA conciliação ativa
    CREATE UNIQUE INDEX uq_extrato_em_uma_conciliacao
        ON conciliacao_itens (extrato_lancamento_id) WHERE ativo AND extrato_lancamento_id IS NOT NULL;
    CREATE INDEX ix_itens_despesa ON conciliacao_itens (despesa_id) WHERE despesa_id IS NOT NULL;
    CREATE INDEX ix_itens_conciliacao ON conciliacao_itens (conciliacao_id);
    """ + _RLS.format(t="conciliacoes") + _RLS.format(t="conciliacao_itens"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS conciliacao_itens; DROP TABLE IF EXISTS conciliacoes;")
