"""Painel: faturamento diário (espelho da Gestão) + correção do sub_itens da ponte do Raio-X

Revision ID: e3f4a5b6c7d8
Revises: d7e8f9a0b1c2
Create Date: 2026-09-29

`vendas_realizado_dia` recebe, por cópia diária SÓ LEITURA, a série `database_realizado_dia.csv`
da Gestão (Datalake). Conferido em 29/09: ago/26 bate dia a dia com o passo "Vendas" do DRE
Interativo do GCOM. Fica até o pipeline de vendas ser portado (Fase 2 do plano).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, None] = "d7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE vendas_realizado_dia (
        id            bigserial PRIMARY KEY,
        tenant_id     bigint NOT NULL REFERENCES tenants(id),
        loja_id       integer NOT NULL REFERENCES lojas(id),
        data          date NOT NULL,
        faturamento   numeric(14,2) NOT NULL,
        tc            integer,                 -- tickets (cupons)
        tm            numeric(12,4),           -- ticket médio
        adc           numeric(12,2),
        beb           numeric(12,2),
        sob           numeric(12,2),
        origem        text,                    -- origem informada pela Gestão (ex.: analitico)
        fonte         text NOT NULL DEFAULT 'gestao_realizado_dia',
        atualizado_em timestamptz NOT NULL DEFAULT now(),
        UNIQUE (loja_id, data, fonte));
    CREATE INDEX ix_vendas_realizado_tenant_data ON vendas_realizado_dia (tenant_id, data);

    ALTER TABLE vendas_realizado_dia ENABLE ROW LEVEL SECURITY;
    ALTER TABLE vendas_realizado_dia FORCE ROW LEVEL SECURITY;
    CREATE POLICY isolamento_tenant ON vendas_realizado_dia
      USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)
      WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint);

    -- a 1ª carga da ponte do Raio-X gravou o valor JSON null onde o Raio-X tem NULL de SQL
    UPDATE despesas SET sub_itens = NULL WHERE json_typeof(sub_itens) = 'null';
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS vendas_realizado_dia;")
