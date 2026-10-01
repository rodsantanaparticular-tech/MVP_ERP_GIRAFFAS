"""Passo 5: banco — contas, importações de extrato e lançamentos (entradas E saídas)

Revision ID: f5a6b7c8d9e0
Revises: e3f4a5b6c7d8
Create Date: 2026-09-30

Parte 1 do modelo 002 (Conciliação de Pagamentos 3 vias). Diferenças em relação ao DDL de referência:
- `extrato_lancamentos.ordem`: posição cronológica do lançamento no dia (o Santander exporta do mais
  novo para o mais antigo; a checagem de saldo corrido precisa da ordem real);
- `extrato_importacoes.saldo_inicial/saldo_final/quebras_saldo`: prova de que o arquivo fecha;
- permissão nova `banco:ler` (extrato é mais sensível que os painéis): admin, franqueado e eng. dados.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f5a6b7c8d9e0"
down_revision: Union[str, None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABELAS_RLS = ["contas_bancarias", "extrato_importacoes", "extrato_lancamentos"]


def upgrade() -> None:
    op.execute("""
    CREATE TABLE contas_bancarias (
        id         bigserial PRIMARY KEY,
        tenant_id  bigint NOT NULL REFERENCES tenants(id),
        loja_id    integer REFERENCES lojas(id),
        banco      text NOT NULL,
        agencia    text,
        conta      text,
        apelido    text NOT NULL,
        ativo      boolean NOT NULL DEFAULT true,
        UNIQUE NULLS NOT DISTINCT (tenant_id, banco, agencia, conta));

    CREATE TABLE extrato_importacoes (
        id             bigserial PRIMARY KEY,
        tenant_id      bigint NOT NULL REFERENCES tenants(id),
        conta_id       bigint NOT NULL REFERENCES contas_bancarias(id),
        arquivo_nome   text NOT NULL,
        arquivo_sha256 char(64) NOT NULL,
        formato        text NOT NULL,
        periodo_de     date,
        periodo_ate    date,
        linhas_lidas   int NOT NULL DEFAULT 0,
        linhas_novas   int NOT NULL DEFAULT 0,
        saldo_inicial  numeric(14,2),
        saldo_final    numeric(14,2),
        quebras_saldo  int NOT NULL DEFAULT 0,
        saldo_confere  boolean NOT NULL,
        importado_por  integer REFERENCES usuarios(id),
        importado_em   timestamptz NOT NULL DEFAULT now(),
        UNIQUE (tenant_id, arquivo_sha256));

    CREATE TABLE extrato_lancamentos (
        id                   bigserial PRIMARY KEY,
        tenant_id            bigint NOT NULL REFERENCES tenants(id),
        conta_id             bigint NOT NULL REFERENCES contas_bancarias(id),
        importacao_id        bigint NOT NULL REFERENCES extrato_importacoes(id),
        data                 date NOT NULL,
        ordem                int NOT NULL,              -- posição cronológica no dia
        historico            text NOT NULL,
        historico_chave      text NOT NULL,             -- LEFT(historico, 33): chave de aprendizado já usada hoje
        documento            text,                      -- Dcto.: NÃO é chave (banco reemite números)
        valor                numeric(14,2) NOT NULL,    -- com sinal: saída < 0
        natureza             char(1) NOT NULL CHECK (natureza IN ('C','D')),
        saldo_informado      numeric(14,2),
        ocorrencia           smallint NOT NULL DEFAULT 1,
        fornecedor_id        bigint REFERENCES fornecedores(id),
        classificacao        text,
        classificacao_origem text CHECK (classificacao_origem IN ('planilha','aprendida','manual')),
        criado_em            timestamptz NOT NULL DEFAULT now(),
        UNIQUE (conta_id, data, historico, valor, ocorrencia));
    CREATE INDEX ix_extrato_conta_data ON extrato_lancamentos (conta_id, data, ordem);
    CREATE INDEX ix_extrato_tenant_data ON extrato_lancamentos (tenant_id, data);
    """)
    for t in TABELAS_RLS:
        op.execute(f"""
        ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {t} FORCE ROW LEVEL SECURITY;
        CREATE POLICY isolamento_tenant ON {t}
          USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)
          WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint);
        """)
    op.execute("""
    INSERT INTO permissoes (codigo, descricao)
      VALUES ('banco:ler', 'Ver contas bancárias, extratos e movimentação de caixa');
    INSERT INTO papel_permissao (papel_id, permissao_id)
      SELECT p.id, pe.id FROM papeis p, permissoes pe
      WHERE pe.codigo = 'banco:ler' AND p.codigo IN ('plataforma_admin', 'franqueado_admin', 'eng_dados');
    """)


def downgrade() -> None:
    op.execute("""
    DELETE FROM papel_permissao WHERE permissao_id = (SELECT id FROM permissoes WHERE codigo = 'banco:ler');
    DELETE FROM permissoes WHERE codigo = 'banco:ler';
    DROP TABLE IF EXISTS extrato_lancamentos, extrato_importacoes, contas_bancarias;
    """)
