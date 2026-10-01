-- =============================================================================
-- 001_tenancy_rbac_credenciais.sql — DDL de REFERÊNCIA (PostgreSQL 16)
--
-- Proposta do modelo multi-tenant + RBAC + cofre de credenciais.
-- Na implementação (Fase 1) isto vira migrações Alembic aplicadas DEPOIS das 6
-- migrações herdadas do Raio-X (lojas, usuarios, usuario_loja, despesas, ...),
-- por isso aqui as tabelas existentes aparecem só como ALTER.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. Tenancy: rede (franqueadora) → tenant (cliente pagante) → loja (unidade)
-- ---------------------------------------------------------------------------
CREATE TABLE redes (
    id            bigserial PRIMARY KEY,
    codigo        text NOT NULL UNIQUE,              -- 'giraffas'
    nome          text NOT NULL,
    criado_em     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE tenants (
    id            bigserial PRIMARY KEY,
    rede_id       bigint NOT NULL REFERENCES redes(id),
    codigo        text NOT NULL UNIQUE,              -- 'rodiza'
    razao_social  text NOT NULL,
    cnpj          varchar(14),
    status        text NOT NULL DEFAULT 'ativo' CHECK (status IN ('onboarding','ativo','suspenso','encerrado')),
    criado_em     timestamptz NOT NULL DEFAULT now()
);

-- tabela `lojas` já existe (Raio-X): ganha tenant e sigla da filial usada nos relatórios GCOM
ALTER TABLE lojas ADD COLUMN tenant_id bigint REFERENCES tenants(id);
ALTER TABLE lojas ADD COLUMN filial_sigla varchar(20);     -- 'GSHBH'
ALTER TABLE lojas ADD COLUMN ativo boolean NOT NULL DEFAULT true;
-- após backfill do tenant da loja existente:
-- ALTER TABLE lojas ALTER COLUMN tenant_id SET NOT NULL;
CREATE UNIQUE INDEX uq_lojas_tenant_sigla ON lojas (tenant_id, filial_sigla);

CREATE TABLE branding (                                  -- white-label
    id            bigserial PRIMARY KEY,
    rede_id       bigint REFERENCES redes(id),
    tenant_id     bigint REFERENCES tenants(id),
    nome_exibicao text,
    logo_url      text,
    cor_primaria  varchar(7),
    cor_secundaria varchar(7),
    dominio       text UNIQUE,
    CHECK (rede_id IS NOT NULL OR tenant_id IS NOT NULL)
);

-- ---------------------------------------------------------------------------
-- 2. RBAC: papéis e permissões em tabela (substitui papel_enum)
-- ---------------------------------------------------------------------------
CREATE TABLE papeis (
    id        bigserial PRIMARY KEY,
    codigo    text NOT NULL UNIQUE,   -- plataforma_admin | ti_ops | eng_dados | franqueado_admin | gestor_loja | auditor | colaborador
    escopo    text NOT NULL CHECK (escopo IN ('plataforma','tenant','loja')),
    descricao text
);

CREATE TABLE permissoes (
    id        bigserial PRIMARY KEY,
    codigo    text NOT NULL UNIQUE,   -- 'modulo:acao'  ex.: conciliacao:ler, credenciais:gravar, jobs:executar, logs:ler
    descricao text
);

CREATE TABLE papel_permissao (
    papel_id     bigint REFERENCES papeis(id) ON DELETE CASCADE,
    permissao_id bigint REFERENCES permissoes(id) ON DELETE CASCADE,
    PRIMARY KEY (papel_id, permissao_id)
);

-- Atribuição: (usuário, papel, escopo). tenant_id/loja_id nulos = escopo mais amplo.
CREATE TABLE usuario_papel (
    id          bigserial PRIMARY KEY,
    usuario_id  bigint NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    papel_id    bigint NOT NULL REFERENCES papeis(id),
    tenant_id   bigint REFERENCES tenants(id),
    loja_id     bigint REFERENCES lojas(id),
    criado_em   timestamptz NOT NULL DEFAULT now(),
    criado_por  bigint REFERENCES usuarios(id),
    UNIQUE NULLS NOT DISTINCT (usuario_id, papel_id, tenant_id, loja_id)
);
-- Migração do legado: usuario_loja(papel=gestor)      → franqueado_admin (tenant) + ti_ops (tenant)
--                     usuario_loja(papel=auditor)     → auditor (loja)
--                     usuario_loja(papel=colaborador) → colaborador (loja)
-- `usuario_loja` fica como view de compatibilidade até o front do Raio-X migrar.

-- ---------------------------------------------------------------------------
-- 3. Catálogo de integrações e conexões por tenant/loja
-- ---------------------------------------------------------------------------
CREATE TABLE integracoes (                     -- catálogo GLOBAL (sem tenant)
    id                 bigserial PRIMARY KEY,
    codigo             text NOT NULL UNIQUE,   -- gcom | cielo_email | cielo_edi | alelo_portal | pluxee_portal | ticket_portal
                                               -- vr_portal | ifood_portal | bradesco_cnab | santander_extrato | gmail_imap | sefaz_nfe
    categoria          text NOT NULL CHECK (categoria IN ('erp','adquirente','voucher','delivery','banco','email','governo','fornecedor','outro')),
    tipo_auth          text NOT NULL,          -- senha | senha_otp_email | api_key | oauth2 | imap_app_password | certificado_a1 | arquivo
    requer_navegador   boolean NOT NULL DEFAULT false,   -- true = só o host agent / perfil rpa executa
    requer_humano      boolean NOT NULL DEFAULT false,   -- captcha/login assistido possível
    schema_parametros  jsonb NOT NULL DEFAULT '{}'::jsonb,  -- JSON Schema dos parâmetros NÃO secretos
    segredos_exigidos  text[] NOT NULL DEFAULT '{}',        -- ex.: {password} | {api_key,client_secret} | {certificado_pfx,certificado_senha}
    ativo              boolean NOT NULL DEFAULT true
);

CREATE TABLE conexoes (
    id                 bigserial PRIMARY KEY,
    tenant_id          bigint NOT NULL REFERENCES tenants(id),
    loja_id            bigint REFERENCES lojas(id),          -- nulo = vale para o tenant todo
    integracao_id      bigint NOT NULL REFERENCES integracoes(id),
    nome               text NOT NULL,
    parametros         jsonb NOT NULL DEFAULT '{}'::jsonb,   -- empresa/usuário GCOM, unidade, CNPJ operador, e-mail… NUNCA senha
    ativo              boolean NOT NULL DEFAULT true,
    ultimo_teste_em    timestamptz,
    ultimo_sucesso_em  timestamptz,
    ultimo_erro        text,
    criado_em          timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (tenant_id, loja_id, integracao_id, nome)
);

-- ---------------------------------------------------------------------------
-- 4. Cofre: envelope encryption (KEK fora do banco → DEK por tenant → segredo)
-- ---------------------------------------------------------------------------
CREATE TABLE tenant_chaves (
    id           bigserial PRIMARY KEY,
    tenant_id    bigint NOT NULL REFERENCES tenants(id),
    versao       int NOT NULL,
    dek_cifrada  bytea NOT NULL,          -- DEK (32 bytes) cifrada com a KEK via AES-256-GCM
    nonce        bytea NOT NULL,
    kek_versao   int NOT NULL,            -- qual chave-mestra embrulhou (permite rotação da KEK)
    ativa        boolean NOT NULL DEFAULT true,
    criado_em    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, versao)
);
CREATE UNIQUE INDEX uq_tenant_chave_ativa ON tenant_chaves (tenant_id) WHERE ativa;

CREATE TABLE credenciais (
    id             bigserial PRIMARY KEY,
    tenant_id      bigint NOT NULL REFERENCES tenants(id),
    conexao_id     bigint NOT NULL REFERENCES conexoes(id) ON DELETE CASCADE,
    tipo           text NOT NULL,         -- password | api_key | client_secret | refresh_token | imap_app_password | certificado_pfx | certificado_senha
    versao         int NOT NULL DEFAULT 1,
    ciphertext     bytea NOT NULL,        -- AES-256-GCM(DEK, valor, AAD = tenant_id|conexao_id|tipo)
    nonce          bytea NOT NULL,        -- 12 bytes, único
    dek_versao     int NOT NULL,
    fingerprint    varchar(64) NOT NULL,  -- HMAC-SHA256 do valor: detecta troca sem expor
    ativo          boolean NOT NULL DEFAULT true,
    expira_em      timestamptz,           -- certificado A1, token OAuth, senha com validade
    criado_em      timestamptz NOT NULL DEFAULT now(),
    criado_por     bigint REFERENCES usuarios(id),
    rotacionado_em timestamptz,
    UNIQUE (conexao_id, tipo, versao)
);
CREATE UNIQUE INDEX uq_credencial_ativa ON credenciais (conexao_id, tipo) WHERE ativo;

CREATE TABLE credencial_acessos (             -- trilha: quem/qual job decifrou
    id             bigserial PRIMARY KEY,
    tenant_id      bigint NOT NULL,
    credencial_id  bigint NOT NULL REFERENCES credenciais(id) ON DELETE CASCADE,
    job_id         bigint,
    usuario_id     bigint REFERENCES usuarios(id),
    finalidade     text NOT NULL,         -- 'job:gcom_extract_diario' | 'teste_conexao'
    criado_em      timestamptz NOT NULL DEFAULT now()
);

-- Nenhum papel de aplicação lê ciphertext diretamente para responder API:
-- a API só expõe metadados (tipo, versão, fingerprint, expira_em). Sugestão:
-- REVOKE SELECT (ciphertext, nonce) ON credenciais FROM erp_api_readonly;

-- ---------------------------------------------------------------------------
-- 5. Parâmetros de negócio por tenant/loja (substituem CSVs de 02_database)
-- ---------------------------------------------------------------------------
CREATE TABLE parametros (                   -- genérico, com vigência
    id              bigserial PRIMARY KEY,
    tenant_id       bigint NOT NULL REFERENCES tenants(id),
    loja_id         bigint REFERENCES lojas(id),
    modulo          text NOT NULL,          -- conciliacao | caixa | vendas | desperdicio | raiox_dre
    chave           text NOT NULL,          -- ex.: tolerancia_centavos
    valor           jsonb NOT NULL,
    vigencia_inicio date NOT NULL DEFAULT CURRENT_DATE,
    vigencia_fim    date,
    atualizado_por  bigint REFERENCES usuarios(id),
    atualizado_em   timestamptz NOT NULL DEFAULT now(),
    CHECK (vigencia_fim IS NULL OR vigencia_fim >= vigencia_inicio)
);
CREATE INDEX ix_parametros_busca ON parametros (tenant_id, modulo, chave, vigencia_inicio DESC);

CREATE TABLE taxas_prazos (                 -- ← gabarito_taxas_prazos.csv + parametros_prazos.csv
    id               bigserial PRIMARY KEY,
    tenant_id        bigint NOT NULL REFERENCES tenants(id),
    loja_id          bigint REFERENCES lojas(id),
    meio             text NOT NULL,         -- Crédito | Débito | Voucher | Pix | iFood
    bandeira_produto text,
    empresa          text NOT NULL,         -- Cielo | Alelo | Pluxee | ...
    taxa_pct         numeric(8,5),
    taxa_contratada_pct numeric(8,5),
    prazo_dias       int,
    tipo_prazo       text CHECK (tipo_prazo IN ('corridos','uteis')),
    banco_destino    text,
    vigencia_inicio  date NOT NULL,
    vigencia_fim     date,
    obs              text
);

CREATE TABLE depara_conciliacao (           -- ← depara_conciliacao.csv
    id             bigserial PRIMARY KEY,
    tenant_id      bigint NOT NULL REFERENCES tenants(id),
    gcom_meio      text NOT NULL,
    gcom_canal     text NOT NULL,
    categoria      text NOT NULL,
    bandeira       text NOT NULL,
    fonte_captura  text,
    observacao     text,
    UNIQUE (tenant_id, gcom_meio, gcom_canal)
);

CREATE TABLE feriados (                     -- ← calendario_feriados.csv (tenant nulo = vale para todos)
    id        bigserial PRIMARY KEY,
    data      date NOT NULL,
    nome      text NOT NULL,
    ambito    text NOT NULL,                -- nacional | estadual | municipal | bancario
    uf        char(2),
    municipio text,
    tenant_id bigint REFERENCES tenants(id),
    UNIQUE NULLS NOT DISTINCT (data, ambito, uf, municipio, tenant_id)
);

-- ---------------------------------------------------------------------------
-- 6. Jobs: fila + histórico (substitui .bat + Agendador + logs .txt)
-- ---------------------------------------------------------------------------
CREATE TABLE jobs (
    id             bigserial PRIMARY KEY,
    tenant_id      bigint NOT NULL REFERENCES tenants(id),
    loja_id        bigint REFERENCES lojas(id),
    tipo           text NOT NULL,           -- gcom.extract_diario | pipeline.abs | pipeline.conciliacao_c2 | ...
    executor       text NOT NULL CHECK (executor IN ('worker','host_agent','rpa_container')),
    status         text NOT NULL DEFAULT 'pendente'
                   CHECK (status IN ('pendente','executando','sucesso','falha','manual_action_required','cancelado')),
    fatal          boolean NOT NULL DEFAULT true,  -- false = como Desperdício hoje: falha não derruba a rodada
    parametros     jsonb NOT NULL DEFAULT '{}'::jsonb,
    agendado_para  timestamptz NOT NULL DEFAULT now(),
    iniciado_em    timestamptz,
    finalizado_em  timestamptz,
    tentativas     int NOT NULL DEFAULT 0,
    max_tentativas int NOT NULL DEFAULT 1,   -- portais com captcha: 1 (não insistir — política atual)
    resultado      jsonb,
    erro           text,
    rodada_id      uuid,                     -- agrupa os passos de uma "rodada diária"
    criado_por     text                      -- 'n8n' | 'usuario:<id>' | 'sistema'
);
-- worker pega o próximo job sem disputa: SELECT ... FOR UPDATE SKIP LOCKED
CREATE INDEX ix_jobs_fila ON jobs (executor, status, agendado_para) WHERE status = 'pendente';

-- rpa_erros (Raio-X) ganha vínculo com tenant e job
ALTER TABLE rpa_erros ADD COLUMN tenant_id bigint REFERENCES tenants(id);
ALTER TABLE rpa_erros ADD COLUMN job_id bigint REFERENCES jobs(id);

-- ---------------------------------------------------------------------------
-- 7. Row-Level Security (defesa em profundidade)
--    A aplicação executa, por request/job:  SET LOCAL app.tenant_id = '<id>';
--    O papel de migração/admin tem BYPASSRLS; o papel da aplicação não.
-- ---------------------------------------------------------------------------
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['conexoes','credenciais','tenant_chaves','credencial_acessos',
                           'parametros','taxas_prazos','depara_conciliacao','jobs']
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format($p$CREATE POLICY isolamento_tenant ON %I
                     USING (tenant_id = current_setting('app.tenant_id', true)::bigint)
                     WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::bigint)$p$, t);
  END LOOP;
END $$;
-- As tabelas de negócio (despesas, vendas, quebra, conciliação...) recebem a mesma
-- política conforme ganharem tenant_id nas migrações da Fase 1/2.
