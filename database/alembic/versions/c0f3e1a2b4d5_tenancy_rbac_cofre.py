"""Etapa 1: tenancy (rede/tenant), perfis de acesso (RBAC), cofre de senhas e RLS

Revision ID: c0f3e1a2b4d5
Revises: 8fe686cb0c97
Create Date: 2026-09-28

Vem DEPOIS das 6 migrações herdadas do Raio-X: um pg_dump do Raio-X restaurado
num banco vazio sobe até aqui sem conversão, e esta migração converte os
papéis antigos (usuario_loja) para o RBAC novo.
"""
import os
from typing import Sequence, Union

from alembic import op

revision: str = "c0f3e1a2b4d5"
down_revision: Union[str, None] = "8fe686cb0c97"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISSOES = {
    "plataforma:admin": "Criar clientes e administrar a plataforma",
    "tenants:gerir": "Gerir lojas do cliente",
    "usuarios:gerir": "Criar usuários e atribuir perfis",
    "conexoes:ler": "Ver conexões de integração",
    "conexoes:gerir": "Criar/alterar conexões de integração",
    "credenciais:metadados": "Ver se a senha existe, versão e validade (nunca o valor)",
    "credenciais:gravar": "Cadastrar/trocar/revogar senhas e chaves",
    "credenciais:revelar": "Ver o valor de uma senha (com motivo, registrado)",
    "logs:ler": "Ler logs e trilha de auditoria",
    "jobs:ler": "Ver rotinas e execuções",
    "jobs:executar": "Disparar/reexecutar rotinas",
    "saude:ler": "Ver saúde dos serviços",
    "dashboards:ler": "Ver dashboards gerenciais",
    "raiox:ler": "Ver o Raio-X do DRE",
    "raiox:auditar": "Auditar lançamentos do Raio-X",
    "raiox:validar": "Validar auditorias do Raio-X",
    "parametros:ler": "Ver parâmetros de negócio",
    "parametros:gerir": "Alterar parâmetros de negócio",
    "conciliacao:ler": "Ver conciliações",
    "conciliacao:operar": "Confirmar/descartar conciliações",
}

PAPEIS = {
    # codigo: (escopo, descricao, permissoes)
    "plataforma_admin": ("plataforma", "Administrador da plataforma", list(PERMISSOES)),
    "ti_ops": ("tenant", "TI / Operações: saúde, logs, rotinas",
               ["logs:ler", "jobs:ler", "jobs:executar", "saude:ler", "conexoes:ler", "credenciais:metadados"]),
    "eng_dados": ("tenant", "Engenharia de Dados: integrações, senhas, parâmetros, conciliação",
                  ["conexoes:ler", "conexoes:gerir", "credenciais:metadados", "credenciais:gravar", "jobs:ler",
                   "jobs:executar", "parametros:ler", "parametros:gerir", "conciliacao:ler", "conciliacao:operar",
                   "logs:ler"]),
    "franqueado_admin": ("tenant", "Franqueado: todas as lojas do cliente, usuários",
                         ["tenants:gerir", "usuarios:gerir", "dashboards:ler", "raiox:ler", "raiox:auditar",
                          "raiox:validar", "parametros:ler", "conciliacao:ler"]),
    "gestor_loja": ("loja", "Gestor da loja: dashboards e Raio-X da própria loja",
                    ["dashboards:ler", "raiox:ler", "raiox:auditar", "conciliacao:ler"]),
    "auditor": ("loja", "Auditor do Raio-X", ["raiox:ler", "raiox:auditar", "dashboards:ler"]),
    "colaborador": ("loja", "Colaborador: leitura do Raio-X", ["raiox:ler"]),
}

# codigo, nome, categoria, tipo_auth, requer_navegador, requer_humano, segredos, parametros obrigatórios
INTEGRACOES = [
    ("gcom", "GCOM (ERP da rede)", "erp", "senha", True, False, ["password"], ["empresa", "usuario"]),
    ("email_imap", "Caixa de e-mail (IMAP)", "email", "imap_app_password", False, False,
     ["imap_app_password"], ["email"]),
    ("cielo_portal", "Cielo — portal", "adquirente", "senha", True, True, ["password"], ["usuario"]),
    ("cielo_edi", "Cielo — API/EDI", "adquirente", "oauth2", False, False, ["client_id", "client_secret"], []),
    ("getnet_portal", "Getnet — portal", "adquirente", "senha", True, True, ["password"], ["usuario"]),
    ("alelo_portal", "Alelo — portal", "voucher", "senha", True, True, ["password"], ["usuario"]),
    ("pluxee_portal", "Pluxee — portal", "voucher", "senha_otp_email", True, True, ["password"], ["usuario"]),
    ("ticket_portal", "Ticket — portal", "voucher", "senha", True, True, ["password"], ["usuario"]),
    ("vr_portal", "VR — portal", "voucher", "senha", True, True, ["password"], ["usuario"]),
    ("ifood_portal", "iFood — Portal do Parceiro", "delivery", "senha_otp_email", True, True, ["password"],
     ["usuario"]),
    ("bradesco_extrato", "Bradesco — extrato (arquivo)", "banco", "arquivo", False, False, [], []),
    ("santander_extrato", "Santander — extrato (arquivo)", "banco", "arquivo", False, False, [], []),
    ("sefaz_certificado_a1", "Certificado digital A1 (SEFAZ/Receita)", "governo", "certificado_a1", False, False,
     ["certificado_pfx", "certificado_senha"], ["cnpj"]),
]

TABELAS_RLS = ["conexoes", "credenciais", "tenant_chaves", "credencial_acessos"]


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def upgrade() -> None:
    op.execute("""
    CREATE TABLE redes (
        id bigserial PRIMARY KEY, codigo text NOT NULL UNIQUE, nome text NOT NULL,
        criado_em timestamptz NOT NULL DEFAULT now());

    CREATE TABLE tenants (
        id bigserial PRIMARY KEY, rede_id bigint NOT NULL REFERENCES redes(id),
        codigo text NOT NULL UNIQUE, razao_social text NOT NULL, cnpj varchar(14),
        status text NOT NULL DEFAULT 'ativo' CHECK (status IN ('onboarding','ativo','suspenso','encerrado')),
        criado_em timestamptz NOT NULL DEFAULT now());

    ALTER TABLE lojas ADD COLUMN tenant_id bigint REFERENCES tenants(id);
    ALTER TABLE lojas ADD COLUMN filial_sigla varchar(20);
    ALTER TABLE lojas ADD COLUMN ativo boolean NOT NULL DEFAULT true;
    CREATE UNIQUE INDEX uq_lojas_tenant_sigla ON lojas (tenant_id, filial_sigla);

    CREATE TABLE papeis (
        id bigserial PRIMARY KEY, codigo text NOT NULL UNIQUE,
        escopo text NOT NULL CHECK (escopo IN ('plataforma','tenant','loja')), descricao text);
    CREATE TABLE permissoes (id bigserial PRIMARY KEY, codigo text NOT NULL UNIQUE, descricao text);
    CREATE TABLE papel_permissao (
        papel_id bigint REFERENCES papeis(id) ON DELETE CASCADE,
        permissao_id bigint REFERENCES permissoes(id) ON DELETE CASCADE,
        PRIMARY KEY (papel_id, permissao_id));
    CREATE TABLE usuario_papel (
        id bigserial PRIMARY KEY,
        usuario_id integer NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        papel_id bigint NOT NULL REFERENCES papeis(id),
        tenant_id bigint REFERENCES tenants(id),
        loja_id integer REFERENCES lojas(id),
        criado_em timestamptz NOT NULL DEFAULT now(),
        criado_por integer REFERENCES usuarios(id),
        CHECK (loja_id IS NULL OR tenant_id IS NOT NULL),
        UNIQUE NULLS NOT DISTINCT (usuario_id, papel_id, tenant_id, loja_id));

    CREATE TABLE integracoes (
        id bigserial PRIMARY KEY, codigo text NOT NULL UNIQUE, nome text NOT NULL,
        categoria text NOT NULL CHECK (categoria IN
            ('erp','adquirente','voucher','delivery','banco','email','governo','fornecedor','outro')),
        tipo_auth text NOT NULL,
        requer_navegador boolean NOT NULL DEFAULT false,
        requer_humano boolean NOT NULL DEFAULT false,
        schema_parametros jsonb NOT NULL DEFAULT '{}'::jsonb,
        segredos_exigidos text[] NOT NULL DEFAULT '{}',
        ativo boolean NOT NULL DEFAULT true);

    CREATE TABLE conexoes (
        id bigserial PRIMARY KEY,
        tenant_id bigint NOT NULL REFERENCES tenants(id),
        loja_id integer REFERENCES lojas(id),
        integracao_id bigint NOT NULL REFERENCES integracoes(id),
        nome text NOT NULL,
        parametros jsonb NOT NULL DEFAULT '{}'::jsonb,
        ativo boolean NOT NULL DEFAULT true,
        ultimo_teste_em timestamptz, ultimo_sucesso_em timestamptz, ultimo_erro text,
        criado_em timestamptz NOT NULL DEFAULT now(),
        UNIQUE NULLS NOT DISTINCT (tenant_id, loja_id, integracao_id, nome));
    CREATE INDEX ix_conexoes_tenant ON conexoes (tenant_id);

    CREATE TABLE tenant_chaves (
        id bigserial PRIMARY KEY, tenant_id bigint NOT NULL REFERENCES tenants(id),
        versao int NOT NULL, dek_cifrada bytea NOT NULL, nonce bytea NOT NULL, kek_versao int NOT NULL,
        ativa boolean NOT NULL DEFAULT true, criado_em timestamptz NOT NULL DEFAULT now(),
        UNIQUE (tenant_id, versao));
    CREATE UNIQUE INDEX uq_tenant_chave_ativa ON tenant_chaves (tenant_id) WHERE ativa;

    CREATE TABLE credenciais (
        id bigserial PRIMARY KEY,
        tenant_id bigint NOT NULL REFERENCES tenants(id),
        conexao_id bigint NOT NULL REFERENCES conexoes(id) ON DELETE CASCADE,
        tipo text NOT NULL, versao int NOT NULL DEFAULT 1,
        ciphertext bytea NOT NULL, nonce bytea NOT NULL, dek_versao int NOT NULL,
        fingerprint varchar(64) NOT NULL, ativo boolean NOT NULL DEFAULT true,
        expira_em timestamptz, criado_em timestamptz NOT NULL DEFAULT now(),
        criado_por integer REFERENCES usuarios(id), rotacionado_em timestamptz,
        UNIQUE (conexao_id, tipo, versao));
    CREATE INDEX ix_credenciais_tenant ON credenciais (tenant_id);
    CREATE UNIQUE INDEX uq_credencial_ativa ON credenciais (conexao_id, tipo) WHERE ativo;

    CREATE TABLE credencial_acessos (
        id bigserial PRIMARY KEY, tenant_id bigint NOT NULL,
        credencial_id bigint NOT NULL REFERENCES credenciais(id) ON DELETE CASCADE,
        job_id bigint, usuario_id integer REFERENCES usuarios(id),
        finalidade text NOT NULL, criado_em timestamptz NOT NULL DEFAULT now());

    ALTER TABLE audit_log ADD COLUMN tenant_id bigint REFERENCES tenants(id);
    ALTER TABLE audit_log ADD COLUMN ip varchar(64);
    CREATE INDEX ix_audit_log_acao_data ON audit_log (acao, criado_em);
    ALTER TABLE rpa_erros ADD COLUMN tenant_id bigint REFERENCES tenants(id);
    """)

    # --- seeds: permissões, papéis, catálogo de integrações -------------------
    for codigo, desc in PERMISSOES.items():
        op.execute(f"INSERT INTO permissoes (codigo, descricao) VALUES ({_q(codigo)}, {_q(desc)})")
    for codigo, (escopo, desc, perms) in PAPEIS.items():
        op.execute(f"INSERT INTO papeis (codigo, escopo, descricao) VALUES ({_q(codigo)}, {_q(escopo)}, {_q(desc)})")
        lista = ",".join(_q(p) for p in perms)
        op.execute(f"""INSERT INTO papel_permissao (papel_id, permissao_id)
                       SELECT p.id, pe.id FROM papeis p, permissoes pe
                       WHERE p.codigo = {_q(codigo)} AND pe.codigo IN ({lista})""")
    for codigo, nome, cat, auth, nav, hum, segredos, obrig in INTEGRACOES:
        seg = "ARRAY[" + ",".join(_q(s) for s in segredos) + "]::text[]" if segredos else "'{}'::text[]"
        schema = '{"required": [' + ", ".join(f'"{o}"' for o in obrig) + "]}"
        op.execute(f"""INSERT INTO integracoes (codigo, nome, categoria, tipo_auth, requer_navegador,
                       requer_humano, segredos_exigidos, schema_parametros)
                       VALUES ({_q(codigo)}, {_q(nome)}, {_q(cat)}, {_q(auth)}, {nav}, {hum}, {seg},
                               {_q(schema)}::jsonb)""")

    # --- legado do Raio-X: lojas sem tenant → rede Giraffas / tenant Rodiza --
    op.execute("""
    DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM lojas WHERE tenant_id IS NULL) THEN
        INSERT INTO redes (codigo, nome) VALUES ('giraffas', 'Giraffas') ON CONFLICT (codigo) DO NOTHING;
        INSERT INTO tenants (rede_id, codigo, razao_social)
          SELECT id, 'rodiza', 'Rodiza Alimentos Ltda' FROM redes WHERE codigo = 'giraffas'
          ON CONFLICT (codigo) DO NOTHING;
        UPDATE lojas SET tenant_id = (SELECT id FROM tenants WHERE codigo = 'rodiza') WHERE tenant_id IS NULL;
      END IF;
    END $$;

    -- gestor → franqueado_admin + ti_ops + eng_dados (escopo do cliente)
    INSERT INTO usuario_papel (usuario_id, papel_id, tenant_id)
      SELECT DISTINCT ul.usuario_id, p.id, l.tenant_id
      FROM usuario_loja ul JOIN lojas l ON l.id = ul.loja_id
      JOIN papeis p ON p.codigo IN ('franqueado_admin', 'ti_ops', 'eng_dados')
      WHERE ul.papel = 'gestor'
    ON CONFLICT DO NOTHING;
    -- auditor / colaborador → mesmo papel, escopo da loja
    INSERT INTO usuario_papel (usuario_id, papel_id, tenant_id, loja_id)
      SELECT ul.usuario_id, p.id, l.tenant_id, l.id
      FROM usuario_loja ul JOIN lojas l ON l.id = ul.loja_id
      JOIN papeis p ON p.codigo = ul.papel::text
      WHERE ul.papel IN ('auditor', 'colaborador')
    ON CONFLICT DO NOTHING;
    """)

    # --- Row-Level Security nas tabelas do cofre ------------------------------
    for t in TABELAS_RLS:
        op.execute(f"""
        ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {t} FORCE ROW LEVEL SECURITY;
        CREATE POLICY isolamento_tenant ON {t}
          USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint)
          WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint);
        """)

    # Descobre o dono de uma conexão sem abrir a linha (só devolve o tenant_id);
    # a API checa a permissão nesse tenant antes de ativar o RLS dele.
    op.execute("""
    CREATE FUNCTION conexao_tenant(p_id bigint) RETURNS bigint
      LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
      AS $$ SELECT tenant_id FROM conexoes WHERE id = p_id $$;
    REVOKE ALL ON FUNCTION conexao_tenant(bigint) FROM PUBLIC;
    """)

    # --- permissões do papel da aplicação (sem superusuário → RLS vale) ------
    papel_app = os.environ.get("APP_DB_USER", "erp_app")
    op.execute(f"""
    DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {_q(papel_app)}) THEN
        EXECUTE 'GRANT USAGE ON SCHEMA public TO {papel_app}';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {papel_app}';
        EXECUTE 'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {papel_app}';
        EXECUTE 'GRANT EXECUTE ON FUNCTION conexao_tenant(bigint) TO {papel_app}';
        EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public
                 GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {papel_app}';
        EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {papel_app}';
        -- catálogo e papéis só mudam por migração
        EXECUTE 'REVOKE INSERT, UPDATE, DELETE ON integracoes, papeis, permissoes, papel_permissao FROM {papel_app}';
        -- trilhas são só-acrescentar
        EXECUTE 'REVOKE UPDATE, DELETE ON audit_log, credencial_acessos FROM {papel_app}';
      END IF;
    END $$;
    """)


def downgrade() -> None:
    op.execute("""
    DROP FUNCTION IF EXISTS conexao_tenant(bigint);
    DROP TABLE IF EXISTS credencial_acessos, credenciais, tenant_chaves, conexoes, integracoes,
                         usuario_papel, papel_permissao, permissoes, papeis CASCADE;
    ALTER TABLE rpa_erros DROP COLUMN IF EXISTS tenant_id;
    DROP INDEX IF EXISTS ix_audit_log_acao_data;
    ALTER TABLE audit_log DROP COLUMN IF EXISTS ip;
    ALTER TABLE audit_log DROP COLUMN IF EXISTS tenant_id;
    DROP INDEX IF EXISTS uq_lojas_tenant_sigla;
    ALTER TABLE lojas DROP COLUMN IF EXISTS ativo;
    ALTER TABLE lojas DROP COLUMN IF EXISTS filial_sigla;
    ALTER TABLE lojas DROP COLUMN IF EXISTS tenant_id;
    DROP TABLE IF EXISTS tenants, redes CASCADE;
    """)
