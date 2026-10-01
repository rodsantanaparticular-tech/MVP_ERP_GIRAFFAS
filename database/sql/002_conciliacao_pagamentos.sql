-- =============================================================================
-- 002_conciliacao_pagamentos.sql — DDL de REFERÊNCIA (PostgreSQL 16)
--
-- Módulo "Conciliação de Pagamentos 3 vias": pedido ↔ extrato bancário ↔ DRE
-- (despesa lançada no GCOM/Raio-X). Depende de 001 + tabelas herdadas do
-- Raio-X (usuarios, lojas, despesas).
--
-- O extrato é importado UMA vez para o módulo `banco` e serve os dois lados:
--   débitos  → esta conciliação de pagamentos
--   créditos → conciliação de recebíveis (Camada 3 do Datalake)
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. Banco: contas, importações idempotentes e lançamentos do extrato
-- ---------------------------------------------------------------------------
CREATE TABLE contas_bancarias (
    id         bigserial PRIMARY KEY,
    tenant_id  bigint NOT NULL REFERENCES tenants(id),
    loja_id    bigint REFERENCES lojas(id),
    banco      text NOT NULL,                  -- Bradesco | Santander
    agencia    text,
    conta      text,
    apelido    text NOT NULL,
    ativo      boolean NOT NULL DEFAULT true,
    UNIQUE NULLS NOT DISTINCT (tenant_id, banco, agencia, conta)
);

CREATE TABLE extrato_importacoes (
    id            bigserial PRIMARY KEY,
    tenant_id     bigint NOT NULL REFERENCES tenants(id),
    conta_id      bigint NOT NULL REFERENCES contas_bancarias(id),
    arquivo_nome  text NOT NULL,
    arquivo_sha256 char(64) NOT NULL,          -- mesmo arquivo 2x = ignora
    formato       text NOT NULL,               -- bradesco_csv | bradesco_xlsx | bradesco_tratado | santander_xlsx
    periodo_de    date,
    periodo_ate   date,
    linhas_lidas  int NOT NULL DEFAULT 0,
    linhas_novas  int NOT NULL DEFAULT 0,
    saldo_confere boolean,                     -- checagem de saldo corrido (regra já usada nos scripts atuais)
    importado_por bigint REFERENCES usuarios(id),
    importado_em  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, arquivo_sha256)
);

CREATE TABLE extrato_lancamentos (
    id               bigserial PRIMARY KEY,
    tenant_id        bigint NOT NULL REFERENCES tenants(id),
    conta_id         bigint NOT NULL REFERENCES contas_bancarias(id),
    importacao_id    bigint NOT NULL REFERENCES extrato_importacoes(id),
    data             date NOT NULL,
    historico        text NOT NULL,            -- "Lançamento" do extrato
    historico_chave  text NOT NULL,            -- LEFT(historico, 33) — chave de aprendizado já usada hoje
    documento        text,                     -- Dcto.: NÃO é chave (banco reemite números)
    valor            numeric(14,2) NOT NULL,   -- com sinal: débito < 0
    natureza         char(1) NOT NULL CHECK (natureza IN ('C','D')),
    saldo_informado  numeric(14,2),
    ocorrencia       smallint NOT NULL DEFAULT 1,  -- desempata lançamentos idênticos no mesmo dia
    fornecedor_id    bigint,                   -- preenchido pela classificação (FK abaixo)
    classificacao    text,                     -- herdada da planilha tratada / aprendida
    classificacao_origem text CHECK (classificacao_origem IN ('planilha','aprendida','manual')),
    criado_em        timestamptz NOT NULL DEFAULT now(),
    -- dedup sem depender do Dcto.: mesma conta+data+histórico+valor+ocorrência = mesma linha
    UNIQUE (conta_id, data, historico, valor, ocorrencia)
);
CREATE INDEX ix_extrato_debitos ON extrato_lancamentos (tenant_id, data) WHERE natureza = 'D';

-- ---------------------------------------------------------------------------
-- 2. Fornecedores e padrões de pagamento (regra reaproveitável por fornecedor)
-- ---------------------------------------------------------------------------
CREATE TABLE fornecedores (
    id         bigserial PRIMARY KEY,
    tenant_id  bigint NOT NULL REFERENCES tenants(id),
    nome       text NOT NULL,                  -- como aparece em despesas.fornecedor (GCOM)
    cnpj       varchar(14),
    apelidos   text[] NOT NULL DEFAULT '{}',   -- variações de nome no GCOM
    UNIQUE (tenant_id, nome)
);
ALTER TABLE extrato_lancamentos
    ADD CONSTRAINT fk_extrato_fornecedor FOREIGN KEY (fornecedor_id) REFERENCES fornecedores(id);

-- Como o texto do extrato identifica o fornecedor (substitui o "aprender pelo LEFT 33")
CREATE TABLE extrato_regras_fornecedor (
    id              bigserial PRIMARY KEY,
    tenant_id       bigint NOT NULL REFERENCES tenants(id),
    padrao_texto    text NOT NULL,             -- prefixo/trecho do histórico
    tipo_match      text NOT NULL DEFAULT 'prefixo' CHECK (tipo_match IN ('prefixo','contem','regex')),
    fornecedor_id   bigint REFERENCES fornecedores(id),
    classificacao   text,
    origem          text NOT NULL CHECK (origem IN ('planilha','manual')),
    UNIQUE (tenant_id, padrao_texto, tipo_match)
);

-- Exemplos: RFG = um_para_um · Kelminas = consolidado_mensal ·
--           Ribeiro = agrupado_vencimento · JM = nota_mais_ajuste
CREATE TABLE padroes_pagamento (
    id                  bigserial PRIMARY KEY,
    tenant_id           bigint NOT NULL REFERENCES tenants(id),
    fornecedor_id       bigint NOT NULL REFERENCES fornecedores(id),
    tipo                text NOT NULL CHECK (tipo IN
                         ('um_para_um','consolidado_mensal','agrupado_vencimento','nota_mais_ajuste','livre')),
    janela_dias_antes   smallint NOT NULL DEFAULT 3,   -- débito pode sair X dias antes do vencimento
    janela_dias_depois  smallint NOT NULL DEFAULT 5,
    tolerancia_valor    numeric(10,2) NOT NULL DEFAULT 0.00,
    ajuste_max_pct      numeric(6,4),                  -- nota_mais_ajuste: diferença aceita (ex.: 0.05 = 5%)
    parametros          jsonb NOT NULL DEFAULT '{}'::jsonb, -- ex.: {"competencia":"mes_anterior"}
    vigencia_inicio     date NOT NULL DEFAULT CURRENT_DATE,
    vigencia_fim        date,
    observacao          text,
    atualizado_por      bigint REFERENCES usuarios(id),
    atualizado_em       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_padroes_fornecedor ON padroes_pagamento (tenant_id, fornecedor_id, vigencia_inicio DESC);

-- ---------------------------------------------------------------------------
-- 3. Conciliações: o "match" e seu status, no mesmo espírito da `auditorias`
-- ---------------------------------------------------------------------------
CREATE TABLE conciliacoes (
    id              bigserial PRIMARY KEY,
    tenant_id       bigint NOT NULL REFERENCES tenants(id),
    loja_id         bigint REFERENCES lojas(id),
    competencia     char(7) NOT NULL,          -- '2026-08' (mês do DRE)
    status          text NOT NULL DEFAULT 'sugerido' CHECK (status IN
                     ('batido','sugerido','pendente','investigar','descartado')),
    padrao_id       bigint REFERENCES padroes_pagamento(id),
    regra_aplicada  text,                      -- qual regra do motor gerou (rastreável)
    total_extrato   numeric(14,2) NOT NULL DEFAULT 0,
    total_despesas  numeric(14,2) NOT NULL DEFAULT 0,
    diferenca       numeric(14,2) GENERATED ALWAYS AS (total_extrato - total_despesas) STORED,
    score           numeric(5,4),              -- confiança do motor (0–1)
    nota            text,
    criado_por      text NOT NULL,             -- 'motor' | 'usuario:<id>'
    criado_em       timestamptz NOT NULL DEFAULT now(),
    confirmado_por  bigint REFERENCES usuarios(id),   -- 'batido' exige confirmação humana ou regra exata
    confirmado_em   timestamptz
);
CREATE INDEX ix_conciliacoes_comp ON conciliacoes (tenant_id, competencia, status);

-- Itens N:M: um débito pode pagar várias despesas (Kelminas), uma despesa pode
-- ser paga em mais de um débito (parcelas); valor_alocado fecha a conta.
-- As 3 vias: 'previsao' (pedido = lançamento PREVISTO no GCOM) · 'despesa'
-- (lançamento real/pago no GCOM = DRE) · 'extrato' (débito no banco).
-- Previsão e despesa são linhas da MESMA tabela `despesas`, com status diferente.
CREATE TABLE conciliacao_itens (
    id                     bigserial PRIMARY KEY,
    conciliacao_id         bigint NOT NULL REFERENCES conciliacoes(id) ON DELETE CASCADE,
    tipo                   text NOT NULL CHECK (tipo IN ('previsao','despesa','extrato')),
    extrato_lancamento_id  bigint REFERENCES extrato_lancamentos(id),
    despesa_id             bigint REFERENCES despesas(id),
    valor_alocado          numeric(14,2) NOT NULL,
    ativo                  boolean NOT NULL DEFAULT true,   -- false quando a conciliação é descartada
    CHECK (
        (tipo = 'extrato' AND extrato_lancamento_id IS NOT NULL AND despesa_id IS NULL) OR
        (tipo IN ('previsao','despesa') AND despesa_id IS NOT NULL AND extrato_lancamento_id IS NULL)
    )
);

-- ---------------------------------------------------------------------------
-- 3b. Ciclo de vida do lançamento no GCOM (substitui a planilha de pedidos)
--     PREVISTO → REAL EM ABERTO / A VENCER / VENCIDO / PENDENTE → PAGO
-- ---------------------------------------------------------------------------
-- Foto de cada extração: permite ver quando a previsão virou real e quando foi paga,
-- e se valor/vencimento mudaram no caminho.
CREATE TABLE despesa_status_historico (
    id            bigserial PRIMARY KEY,
    despesa_id    bigint NOT NULL REFERENCES despesas(id) ON DELETE CASCADE,
    status_gcom   text NOT NULL,
    valor         numeric(14,2),
    venc          date,
    visto_em      timestamptz NOT NULL DEFAULT now(),
    job_id        bigint                      -- extração que observou
);
CREATE INDEX ix_despesa_hist ON despesa_status_historico (despesa_id, visto_em);

-- Confirmado no GCOM ao vivo (28/09/2026, teste assistido): previsão é o MESMO
-- documento com a chave "Previsão" ligada. Ao efetivar, o documento continua o
-- mesmo (mesmo Nº, mesma linha) e o status passa de "Previsto" para "Real";
-- o caminho inverso também existe. Por isso não há vínculo previsão→real:
-- o ciclo de vida é o histórico de status da própria despesa.
--
-- Previsão abandonada (pedido cancelado) é EXCLUÍDA no GCOM ("Excluir Previsões")
-- e some da origem; documento real só pode ser CANCELADO. A extração marca como
-- sumido o que estava PREVISTO e não voltou, em vez de apagar a linha aqui.
ALTER TABLE despesas ADD COLUMN sumiu_da_origem_em timestamptz;

-- DRE (Raio-X) conta só o realizado: previsão NÃO é despesa do DRE (evita contar 2x).
CREATE VIEW vw_despesas_dre AS
    SELECT * FROM despesas WHERE status_gcom <> 'PREVISTO' AND sumiu_da_origem_em IS NULL;
CREATE VIEW vw_previsoes_abertas AS           -- pedidos ainda não efetivados
    SELECT * FROM despesas WHERE status_gcom = 'PREVISTO' AND sumiu_da_origem_em IS NULL;
-- um débito do extrato só pode estar em UMA conciliação ativa
CREATE UNIQUE INDEX uq_extrato_em_uma_conciliacao
    ON conciliacao_itens (extrato_lancamento_id) WHERE ativo AND extrato_lancamento_id IS NOT NULL;
CREATE INDEX ix_itens_despesa ON conciliacao_itens (despesa_id) WHERE despesa_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 4. RLS (mesma política do 001)
-- ---------------------------------------------------------------------------
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['contas_bancarias','extrato_importacoes','extrato_lancamentos','fornecedores',
                           'extrato_regras_fornecedor','padroes_pagamento','conciliacoes']
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format($p$CREATE POLICY isolamento_tenant ON %I
                     USING (tenant_id = current_setting('app.tenant_id', true)::bigint)
                     WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::bigint)$p$, t);
  END LOOP;
END $$;
-- conciliacao_itens herda o isolamento via conciliacoes (acesso sempre pelo pai no service).
