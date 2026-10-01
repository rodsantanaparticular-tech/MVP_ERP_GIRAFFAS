"""Passo 5c-2: classe do extrato → categoria do DRE (visão CAIXA do painel de fornecedores)

Revision ID: b8c9d0e1f2a3
Revises: a6b7c8d9e0f1
Create Date: 2026-09-30

- `extrato_categorias`: a classificação do extrato (a da planilha do usuário: INSUMO, FOLHA, REFIN...)
  vira a categoria do GCOM (Tipo de Desembolso: INSUMOS, PESSOAL, DESPESAS FINANCEIRAS...), para a visão
  caixa ser comparável com a competência. `favorecido` NULL = vale para qualquer favorecido; preenchido =
  exceção (ex.: DESPESA + GAS → UTILIDADES). `grupo`: despesa (entra no total), receita (vendas
  recebidas), fora_dre (transferência entre contas, aporte, retirada) ou outra_entrada.
- `extrato_regras.classificacoes`: as classes que a planilha já deu para aquele texto. Quando a regra não
  decide a classe (ex.: Pix de funcionário = FOLHA ou ADIANTAMENTO ou DOBRA), mas todas caem na mesma
  categoria do DRE (PESSOAL), o painel usa essa categoria.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a6b7c8d9e0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE extrato_categorias (
        id             bigserial PRIMARY KEY,
        tenant_id      bigint NOT NULL REFERENCES tenants(id),
        natureza       char(1) NOT NULL CHECK (natureza IN ('C','D')),
        classificacao  text NOT NULL,
        favorecido     text,
        categoria      text NOT NULL,
        grupo          text NOT NULL CHECK (grupo IN ('despesa','receita','fora_dre','outra_entrada')),
        atualizado_por integer REFERENCES usuarios(id),
        atualizado_em  timestamptz NOT NULL DEFAULT now(),
        UNIQUE NULLS NOT DISTINCT (tenant_id, natureza, classificacao, favorecido));

    ALTER TABLE extrato_categorias ENABLE ROW LEVEL SECURITY;
    ALTER TABLE extrato_categorias FORCE ROW LEVEL SECURITY;
    CREATE POLICY isolamento_tenant ON extrato_categorias
      USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)
      WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint);

    ALTER TABLE extrato_regras ADD COLUMN classificacoes text[] NOT NULL DEFAULT '{}';
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE extrato_regras DROP COLUMN classificacoes;
    DROP TABLE IF EXISTS extrato_categorias;
    """)
