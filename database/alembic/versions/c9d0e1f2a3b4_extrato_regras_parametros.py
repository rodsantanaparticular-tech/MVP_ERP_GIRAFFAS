"""Passo 5c-2: parâmetros nas regras do extrato (calendário de pagamento por favorecido)

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-09-30

`extrato_regras.parametros` (jsonb). Primeiro uso: o calendário da franqueadora, informado pelo usuário
em 30/09 — o mesmo texto de boleto ("COBRANCA GIRAFFAS") é REFIN (valores fixos), ROYALTIES (vence dia 20)
ou FUNDO MKT (vence no último dia do mês); em fim de semana/feriado paga no próximo dia útil. Quem decide é a
data e o valor, não o texto. Ver `modules/banco/classificacao.py::aplicar_calendarios`.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE extrato_regras ADD COLUMN parametros jsonb NOT NULL DEFAULT '{}'::jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE extrato_regras DROP COLUMN parametros")
