"""Fase 1B, passo 1: CRM de fornecedores, padrões de pagamento e despesas recorrentes

Revision ID: d7e8f9a0b1c2
Revises: c0f3e1a2b4d5
Create Date: 2026-09-29

Primeira parte do modelo 002 (Conciliação de Pagamentos 3 vias) que não depende
de extrato nem de despesas: o cadastro de fornecedores vira DADO do IN-360
(decisão do usuário, 28/09) e a planilha CRM_Fornecedores_Rodiza.xlsx passa a
ser relatório gerado a partir daqui. Extrato, regras de texto do extrato e
conciliações entram nos próximos passos.

Diferenças em relação ao DDL de referência 002:
- `fornecedores` ganha os campos do CRM (razão social, categoria, prazo, etc.);
- `padroes_pagamento` só pode ter UM padrão vigente por fornecedor;
- `despesas_recorrentes` é nova (as "despesas fixas" do CRM: dia e faixa de valor).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, None] = "c0f3e1a2b4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABELAS_RLS = ["fornecedores", "padroes_pagamento", "despesas_recorrentes"]


def upgrade() -> None:
    op.execute("""
    CREATE TABLE fornecedores (
        id              bigserial PRIMARY KEY,
        tenant_id       bigint NOT NULL REFERENCES tenants(id),
        nome            text NOT NULL,              -- nome curto do dia a dia (ex.: Kelminas)
        razao_social    text,
        cnpj            varchar(14) CHECK (cnpj ~ '^[0-9]{14}$'),
        categoria       text,
        apelidos        text[] NOT NULL DEFAULT '{}',  -- como aparece no GCOM / no extrato (ex.: "MB")
        prazo_pagamento text,                       -- descrição livre do combinado
        endereco        text,
        observacoes     text,
        ativo           boolean NOT NULL DEFAULT true,
        criado_em       timestamptz NOT NULL DEFAULT now(),
        atualizado_em   timestamptz NOT NULL DEFAULT now(),
        atualizado_por  integer REFERENCES usuarios(id),
        UNIQUE (tenant_id, nome));
    CREATE UNIQUE INDEX uq_fornecedores_cnpj ON fornecedores (tenant_id, cnpj) WHERE cnpj IS NOT NULL;

    -- RFG = um_para_um · Kelminas = consolidado_mensal ·
    -- Ribeiro = agrupado_vencimento · JM = nota_mais_ajuste
    CREATE TABLE padroes_pagamento (
        id                  bigserial PRIMARY KEY,
        tenant_id           bigint NOT NULL REFERENCES tenants(id),
        fornecedor_id       bigint NOT NULL REFERENCES fornecedores(id),
        tipo                text NOT NULL CHECK (tipo IN
                             ('um_para_um','consolidado_mensal','agrupado_vencimento','nota_mais_ajuste','livre')),
        janela_dias_antes   smallint NOT NULL DEFAULT 3 CHECK (janela_dias_antes >= 0),
        janela_dias_depois  smallint NOT NULL DEFAULT 5 CHECK (janela_dias_depois >= 0),
        tolerancia_valor    numeric(10,2) NOT NULL DEFAULT 0.00 CHECK (tolerancia_valor >= 0),
        ajuste_max_pct      numeric(6,4) CHECK (ajuste_max_pct IS NULL OR ajuste_max_pct BETWEEN 0 AND 1),
        parametros          jsonb NOT NULL DEFAULT '{}'::jsonb,
        vigencia_inicio     date NOT NULL DEFAULT CURRENT_DATE,
        vigencia_fim        date,
        observacao          text,
        atualizado_por      integer REFERENCES usuarios(id),
        atualizado_em       timestamptz NOT NULL DEFAULT now(),
        CHECK (vigencia_fim IS NULL OR vigencia_fim >= vigencia_inicio));
    CREATE UNIQUE INDEX uq_padrao_vigente ON padroes_pagamento (fornecedor_id) WHERE vigencia_fim IS NULL;
    CREATE INDEX ix_padroes_fornecedor ON padroes_pagamento (tenant_id, fornecedor_id, vigencia_inicio DESC);

    -- O que se espera ver sair todo mês (dia e faixa de valor). Serve para
    -- alertar despesa fixa que não apareceu ou veio fora da faixa.
    CREATE TABLE despesas_recorrentes (
        id              bigserial PRIMARY KEY,
        tenant_id       bigint NOT NULL REFERENCES tenants(id),
        fornecedor_id   bigint REFERENCES fornecedores(id),   -- vazio = tarifa do próprio banco etc.
        descricao       text NOT NULL,
        dia_inicio      smallint NOT NULL CHECK (dia_inicio BETWEEN 1 AND 31),
        dia_fim         smallint NOT NULL CHECK (dia_fim BETWEEN 1 AND 31),
        valor_min       numeric(14,2) CHECK (valor_min IS NULL OR valor_min >= 0),
        valor_max       numeric(14,2),
        valor_variavel  boolean NOT NULL DEFAULT false,         -- ex.: royalties (% do faturamento)
        vigencia_fim    date,                                   -- ex.: última parcela já paga
        observacao      text,
        ativo           boolean NOT NULL DEFAULT true,
        atualizado_por  integer REFERENCES usuarios(id),
        atualizado_em   timestamptz NOT NULL DEFAULT now(),
        UNIQUE (tenant_id, descricao),
        CHECK (dia_fim >= dia_inicio),
        CHECK (valor_max IS NULL OR valor_min IS NULL OR valor_max >= valor_min));
    """)

    for t in TABELAS_RLS:
        op.execute(f"""
        ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {t} FORCE ROW LEVEL SECURITY;
        CREATE POLICY isolamento_tenant ON {t}
          USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)
          WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint);
        """)
    # Os GRANTs ao papel da aplicação vêm do ALTER DEFAULT PRIVILEGES da c0f3e1a2b4d5.


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS despesas_recorrentes, padroes_pagamento, fornecedores CASCADE;")
