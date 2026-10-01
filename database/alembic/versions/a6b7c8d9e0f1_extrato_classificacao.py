"""Passo 5c: quem recebeu cada saída (e quem mandou cada entrada) do extrato

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
Create Date: 2026-09-30

Parte 2 do modelo 002. Diferenças em relação ao DDL de referência (`extrato_regras_fornecedor`):
- a tabela se chama `extrato_regras` porque o favorecido nem sempre é fornecedor do CRM (funcionário,
  sócio, banco, imposto): `favorecido` é obrigatório e `fornecedor_id` é opcional;
- `natureza` (C/D): o mesmo texto pode ter sentidos diferentes na entrada e na saída;
- `classificacao` pode ficar NULL: o texto do banco diz QUEM recebeu, nem sempre O QUE foi pago
  (ex.: o boleto "COBRANCA GIRAFFAS" é royalties, fundo de marketing ou REFIN). Quem decide é o
  match com a despesa do GCOM ou um humano;
- `extrato_lancamentos.favorecido` e `regra_id`; `classificacao_origem` ganha 'sistema'
  (transferência entre contas próprias, achada pelo par saída ↔ entrada).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a6b7c8d9e0f1"
down_revision: Union[str, None] = "f5a6b7c8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE extrato_regras (
        id             bigserial PRIMARY KEY,
        tenant_id      bigint NOT NULL REFERENCES tenants(id),
        padrao_texto   text NOT NULL,             -- LEFT(histórico, 33), a chave de aprendizado já usada
        tipo_match     text NOT NULL DEFAULT 'prefixo' CHECK (tipo_match IN ('prefixo','contem','regex')),
        natureza       char(1) NOT NULL CHECK (natureza IN ('C','D')),
        favorecido     text NOT NULL,
        fornecedor_id  bigint REFERENCES fornecedores(id),
        classificacao  text,                      -- NULL = o texto não decide (ver docstring)
        origem         text NOT NULL CHECK (origem IN ('planilha','manual')),
        ocorrencias    int NOT NULL DEFAULT 0,    -- quantas linhas da planilha sustentam a regra
        ativo          boolean NOT NULL DEFAULT true,
        atualizado_por integer REFERENCES usuarios(id),
        atualizado_em  timestamptz NOT NULL DEFAULT now(),
        UNIQUE (tenant_id, padrao_texto, tipo_match, natureza));

    ALTER TABLE extrato_regras ENABLE ROW LEVEL SECURITY;
    ALTER TABLE extrato_regras FORCE ROW LEVEL SECURITY;
    CREATE POLICY isolamento_tenant ON extrato_regras
      USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)
      WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint);

    ALTER TABLE extrato_lancamentos
      ADD COLUMN favorecido text,
      ADD COLUMN regra_id bigint REFERENCES extrato_regras(id),
      DROP CONSTRAINT extrato_lancamentos_classificacao_origem_check,
      ADD CONSTRAINT extrato_lancamentos_classificacao_origem_check
        CHECK (classificacao_origem IN ('planilha','aprendida','manual','sistema'));
    CREATE INDEX ix_extrato_fornecedor ON extrato_lancamentos (tenant_id, fornecedor_id, data);
    """)


def downgrade() -> None:
    op.execute("""
    DROP INDEX IF EXISTS ix_extrato_fornecedor;
    UPDATE extrato_lancamentos SET classificacao_origem = NULL WHERE classificacao_origem = 'sistema';
    ALTER TABLE extrato_lancamentos
      DROP CONSTRAINT extrato_lancamentos_classificacao_origem_check,
      ADD CONSTRAINT extrato_lancamentos_classificacao_origem_check
        CHECK (classificacao_origem IN ('planilha','aprendida','manual')),
      DROP COLUMN regra_id,
      DROP COLUMN favorecido;
    DROP TABLE IF EXISTS extrato_regras;
    """)
