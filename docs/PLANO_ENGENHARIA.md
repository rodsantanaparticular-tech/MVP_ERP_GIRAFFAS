# Plano de Engenharia — ERP IN-360 (MVP) · Unificação em Monólito Modular

**Data:** 28/09/2026 · **Status:** proposta (nada foi alterado nas pastas de origem)

Fontes analisadas (leitura estática, somente leitura):

| Apelido neste plano | Pasta | O que é hoje |
|---|---|---|
| **P1 — Datalake** | `G:\Meu Drive\1-RSIN(holding)\3-Rodiza - Giraffas\Gestao\Giraffas-Datalake` (+ `CONCILIACAO_FINANCEIRO/`, `Controle_Caixa_Pedidos/`) | Python + pandas + Playwright. Relatórios GCOM/adquirentes → CSV em `02_database/` → dashboards HTML (Chart.js) publicados no Cloudflare Pages. Orquestrado por `.bat` + Agendador do Windows. Sem banco, sem API, sem login. |
| **P2 — Raio-X / IN-360** | `C:\Users\rodsa\OneDrive\Documentos\GESTÃO_GIRAFFAS\in-360-giraffas` (+ scripts soltos na raiz) | FastAPI + PostgreSQL 16 + Alembic em Docker Compose. JWT, papéis por loja, `audit_log`, `rpa_erros`. Front-end de arquivo único (Raio-X do DRE). RPA do GCOM roda fora do Docker. |

---

## 0. Diagnóstico estrutural — o que define a arquitetura

Seis constatações da leitura do código mudam o desenho:

1. **As duas bases se complementam.** P2 já tem o que P1 não tem: banco relacional, API, autenticação, papéis por loja, `loja_id` em toda tabela, log de auditoria e migrações. P1 tem o que P2 não tem: 13 parsers de fontes financeiras, 7 pipelines de indicadores, 8 conectores de extração e 6 dashboards. **Decisão:** P2 vira o esqueleto (core/api/database) e P1 é portado para dentro como módulos de pipeline e automação.

2. **O RPA não roda num contêiner Linux headless comum.** Os dois projetos registram que o GCOM tem WAF que bloqueia navegador headless (`headless=False` obrigatório) e que Pluxee/Alelo/VR/Ticket exigem sessão salva em perfil do Chrome + captcha resolvido por humano. Por decisão já registrada no P1, **não há serviço de quebra de captcha, e isso continua valendo.** Consequência: a camada `automations/` precisa de um **executor com navegador visível**. Nas fases iniciais, esse executor é um agente no Windows. Um contêiner com Xvfb + noVNC entra como experimento controlado (seção 4).

3. **Caminhos e identidade da loja estão fixos no código.** Nove scripts do P1 têm `ROOT = Path(r"G:\Meu Drive\...")`. Os conectores fixam empresa/usuário do GCOM, e-mail, CNPJ, CPF do operador e unidade "SHOPPING BH". Hoje isso é o principal bloqueio para multi-tenant. A lógica não precisa mudar, só a **origem** desses valores (configuração + cofre).

4. **As credenciais vivem no Gerenciador de Credenciais do Windows (`keyring`).** É seguro para um usuário numa máquina, mas não serve para contêineres nem para vários clientes. É preciso um cofre por tenant, e um adaptador faz os conectores lerem do cofre sem mudar o resto do código.

5. **Riscos operacionais atuais, que o novo desenho precisa corrigir:**
   - O Postgres do P2 grava `./pgdata` **dentro do OneDrive**, e a sincronização de arquivos de banco vivos pode corromper dados. O novo repositório também está no OneDrive, então **nenhum dado vivo pode ficar dentro dele** (ver `DATA_DIR`).
   - A tarefa agendada das 07:00 falha quando a máquina dorme (registrado no STATUS do P1). 24x7 exige host sempre ligado.
   - Os dashboards de P1 com dados financeiros são publicados no Cloudflare Pages, **provavelmente sem login** (o STATUS registra "login na entrada" como pendente). **Confirmar.** Se estiverem públicos, é a exposição mais urgente.
   - O `docker-compose.yml` do P2 usa senha padrão no Postgres, expõe a porta no host e roda `uvicorn --reload`. Isso serve para desenvolvimento, não para produção.
   - `database_vendas.csv` tem **107 MB** e é relido inteiro a cada rodada. No Postgres vira tabela particionada por mês.

6. **O P2 já espera a unificação.** O STATUS do P2 tem a seção "Contexto pro próximo passo: unificar Performance + Financeiro + Auditoria", e o README do P2 diz que a API é "fonte de verdade" dos módulos futuros. Este plano executa essa intenção.

---

## 1. Mapeamento de reutilização

Legenda: 🟢 reaproveita quase igual · 🟡 reaproveita a lógica, trocando entrada/saída · 🔴 não migra (arquivar)

### 1.1 Do P2 (Raio-X / IN-360) → esqueleto do sistema

| Artefato de origem | Destino | Nível | O que muda |
|---|---|---|---|
| `app/config.py`, `app/database.py` | `core/config.py`, `core/db.py` | 🟢 | + leitura de Docker secrets, + contexto de tenant na sessão |
| `app/auth.py` (bcrypt + JWT) | `core/security/auth.py` | 🟢 | `exige_gestor` vira `exige_permissao("...")` (RBAC granular) |
| `app/models.py`: `Loja`, `Usuario`, `UsuarioLoja`, `AuditLog`, `RpaErro`, `SyncSession` | `modules/identity/`, `modules/tenants/`, `modules/ops/` | 🟢 | `lojas` ganha `tenant_id`, `papel_enum` vira tabelas de papéis e permissões (seção 3) |
| `Despesa`, `Auditoria`, `RegraClassificacao` + routers | `modules/raiox_dre/` | 🟢 | Nenhuma regra muda. `regras_classificacao` ganha `tenant_id` |
| `alembic/versions/*` (6 migrações) | `database/alembic/versions/` | 🟢 | Mantidas **na mesma ordem**. As novas tabelas entram como migrações seguintes, e o banco atual restaura por `pg_dump` sem conversão |
| `frontend/index.html` (Raio-X, 1.981 linhas) | `dashboards/raiox/index.html` | 🟢 | Só a URL base da API. `REF_POR_MES` (faturamento/entrada fixos no JS) passa a vir de `modules/vendas` |
| `scripts/gcom_extract_despesas.py`, `gcom_aplicar_classificacao.py`, `gcom_servico_local.py` | `automations/connectors/gcom/` | 🟡 | `keyring` vira `CredentialProvider`, `API_BASE` fixo vira config. Escrita no GCOM **continua exigindo confirmação humana** |
| `reconcilia_extracao.py`, `reagrupa_sub_itens.py`, `migrar_novos_meses.py`, `seed_and_migrate.py` | `automations/jobs/raiox/` | 🟡 | Já existe pendência conhecida: `reconcilia_extracao.py` não entende `sub_itens`, então só roda em modo simulação até ser corrigido |
| `backups/*.sql` | carga inicial do novo banco | 🟢 | `pg_restore` para o banco `erp` |
| `atualiza_bradesco_jul_ago_2026.py` (raiz) | `pipelines/transforms/banco_classificacao.py` | 🟡 | O algoritmo de "aprender classificação pelo histórico (LEFT 33)" + checagem de saldo corrido vira job reutilizável, e a planilha deixa de ser a base |
| `pgdata/`, `uploads/`, `.env` | — | 🔴 | Dados vivos não se copiam, migra-se por dump. `.env` é recriado com segredos novos |

### 1.2 Do P1 (Datalake) → módulos de pipeline, automação e dashboards

| Artefato de origem | Destino | Nível | O que muda |
|---|---|---|---|
| `04_scripts/conciliacao_fontes/*.py` (13 parsers: Cielo, Alelo, Pluxee, Ticket, VR, iFood, Getnet, Bradesco, Santander…) | `pipelines/parsers/` | 🟢 | Já são funções puras (arquivo → DataFrame). Só muda o pacote |
| `pipeline.py` (ABS), `pipeline_quebra.py`, `pipeline_meta.py`, `pipeline_desperdicio.py`, `pipeline_conciliacao.py`, `pipeline_camada3.py`, `pipeline_central.py` | `pipelines/transforms/<modulo>.py` + `pipelines/loaders/` | 🟡 | Cada script é separado em 3 partes: **parse** (igual), **regra** (igual: `kpis`, `monta_camada2`, `monta_camada3`, `_merge`, dedup "arquivo mais recente vence", provisório etc.) e **I/O** (CSV passa a ser tabela Postgres, `ROOT` fixo passa a ser config) |
| `extract_diario.py`, `extract_desperdicio.py`, `extract_mapa_caixa.py` (GCOM) | `automations/connectors/gcom/` | 🟡 | Mesmo fluxo Playwright headful. Empresa, usuário e unidade saem da conexão do tenant |
| `extract_email_conciliacao.py` (Cielo por e-mail/IMAP) | `automations/connectors/cielo_email/` | 🟡 | É o **primeiro candidato a rodar 100% em contêiner** (não usa navegador) |
| `extract_alelo.py`, `extract_pluxee.py`, `05_automacao/staging/*_login_assistido.py` | `automations/connectors/<portal>/` | 🟡 | Continuam "assistidos". CPF/CNPJ/e-mail fixos saem do código para a conexão do tenant |
| `captcha_provider.py`, `_gmail_inbox.py`, `_stealth.py` | `automations/shared/` | 🟢 | `ManualActionRequired` (exit 2) vira status de job `manual_action_required`, visível para TI |
| `configurar_credenciais.py` | `automations/tools/importar_keyring.py` | 🟡 | Vira ferramenta **única** de migração: lê do keyring local e grava no cofre pela API |
| `template_dashboard_*.html` + `chart.umd.min.js` + `montar_menu_dashboards.py` | `dashboards/templates/` + `dashboards/builder.py` | 🟡 | Os mesmos HTML, agora servidos pela API **atrás de login**. O JSON embutido passa a vir de endpoint por loja |
| `02_database/depara_conciliacao.csv`, `gabarito_taxas_prazos.csv`, `parametros_prazos.csv`, `calendario_feriados.csv`, `categorias_produtos.csv`, `produtos_grupo.csv` | `database/seeds/` → tabelas de parâmetros por tenant | 🟡 | Parâmetros de negócio deixam de ser CSV global e passam a ser por tenant/loja, com vigência |
| `02_database/database_*.csv` (histórico) | carga inicial das tabelas | 🟢 | Carga única + **dataset de referência** dos testes de paridade (seção 5) |
| `executar_tudo.bat` + `ATUALIZAR_*.bat` | `n8n/workflows/` + `jobs` | 🟡 | A mesma sequência e as mesmas regras (Desperdício "não fatal", conferência das bases no fim) viram workflow. A tabela `jobs` guarda o histórico |
| `01_entrada/GUIA_EXTRACAO.md`, `05_automacao/COMO_AUTOMATIZAR.md`, `RUNBOOK_automacao.html` | `docs/runbooks/` | 🟢 | Referência operacional para TI |
| `*.bak_*`, `__pycache__/`, `.wrangler/`, `extract_vendas_periodo.py`, `CONCILIACAO_FINANCEIRA.bat` (declarados obsoletos no STATUS) | — | 🔴 | Não migram |
| `05_automacao/browser_profile_*` | — | 🔴 | **São segredos** (sessões logadas). Não entram no repositório. O executor RPA recria os perfis em volume próprio |
| `Controle_Caixa_Pedidos/*.xlsm`, `CONCILIACAO_FINANCEIRO/*` | — (backlog) | 🔴 | Planilhas manuais e análises pontuais (ICMS-ST). Candidatas a módulo futuro, fora do MVP |

---

## 2. Nova árvore de diretórios (monólito modular)

Princípios: **um** pacote Python e **uma** imagem de aplicação usada em papéis diferentes (api, worker, console). Um módulo só fala com outro pela interface `service.py` e nunca importa `models.py` alheio. Dado vivo **nunca** fica dentro do repositório.

```
MVP_ERP_GIRAFFAS/                     ← repositório (código + docs; no OneDrive só código)
├── CLAUDE.md · STATUS.md · README.md
├── docker-compose.yml                ← produção local 24x7 (entregue)
├── docker-compose.override.yml       ← dev: hot-reload, portas extras (Fase 1)
├── .env.example                      ← entregue · .env real NUNCA commitado
├── pyproject.toml                    ← um pacote, dependências por "extra": api | worker | rpa
│
├── core/                             ← infraestrutura compartilhada, sem regra de negócio
│   ├── config.py                     ← Settings (env + /run/secrets)
│   ├── db.py                         ← engine, sessão, SET app.tenant_id por request/job
│   ├── tenancy.py                    ← resolve tenant/loja do usuário ou do job
│   ├── security/
│   │   ├── auth.py                   ← JWT + bcrypt (vem do P2)
│   │   ├── rbac.py                   ← exige_permissao("conciliacao:ler", loja_id=...)
│   │   └── vault.py                  ← cifragem envelope AES-256-GCM (seção 3)
│   ├── audit.py                      ← grava audit_log (vem do P2)
│   └── logging.py                    ← log JSON com tenant_id/job_id em toda linha
│
├── modules/                          ← domínios de negócio (cada um: models, schemas, service, router)
│   ├── tenants/                      ← redes, tenants, lojas, branding (white-label)
│   ├── identity/                     ← usuários, papéis, permissões, atribuições
│   ├── integrations/                 ← catálogo de integrações, conexões, credenciais (cofre)
│   ├── parametros/                   ← parâmetros por tenant/loja com vigência, taxas, prazos, de-para, feriados
│   ├── vendas/                       ← ABS, realizado diário, metas              (P1)
│   ├── caixa/                        ← quebra de caixa / encontro de caixa       (P1)
│   ├── desperdicio/                  ← desperdício & break                       (P1)
│   ├── conciliacao/                  ← camadas 1/2/3 + central                   (P1)
│   ├── raiox_dre/                    ← despesas, auditorias, regras, sync GCOM   (P2)
│   └── ops/                          ← jobs, rpa_erros, execuções, saúde          (P2 + novo)
│
├── api/
│   ├── main.py                       ← monta os routers de modules/*, /health, /metrics
│   └── deps.py
│
├── pipelines/                        ← ETL puro: arquivo/DataFrame → tabelas (sem HTTP, sem navegador)
│   ├── parsers/                      ← conciliacao_fontes/* do P1, sem mudança de lógica
│   ├── transforms/                   ← regras dos pipeline_*.py do P1
│   ├── loaders/                      ← upsert idempotente no Postgres por (tenant, loja, data, fonte…)
│   └── registry.py                   ← "tipo de job" → função
│
├── automations/                      ← tudo que fala com sistema externo
│   ├── shared/                       ← captcha_provider, gmail_inbox, stealth, credential_provider
│   ├── connectors/
│   │   ├── gcom/                     ← extract_diario, desperdício, mapa caixa, despesas DRE, aplicar classificação
│   │   ├── cielo_email/              ← IMAP (roda em contêiner)
│   │   ├── alelo/ · pluxee/ · ticket/ · vr/ · ifood/
│   │   └── bancos/                   ← Bradesco/Santander (preferir CNAB/extrato eletrônico, não RPA)
│   ├── runner/
│   │   ├── worker.py                 ← consome jobs sem navegador (dentro do Docker)
│   │   └── host_agent.py             ← consome jobs com navegador (Windows, fora do Docker)
│   └── tools/importar_keyring.py
│
├── dashboards/
│   ├── templates/                    ← template_dashboard_*.html + chart.umd.min.js (P1)
│   ├── raiox/                        ← index.html (P2)
│   ├── builder.py                    ← montar_menu_dashboards (P1), agora por tenant
│   └── console/                      ← Streamlit: console de TI / Eng. de Dados
│
├── database/
│   ├── alembic/ + alembic.ini        ← migrações do P2 + novas
│   ├── sql/                          ← DDL de referência, views, políticas RLS (entregue: 001_*)
│   ├── init/                         ← scripts do 1º boot do Postgres (cria banco do n8n) (entregue)
│   └── seeds/                        ← CSVs de parâmetros do P1 → carga por tenant
│
├── n8n/workflows/                    ← workflows exportados (JSON) versionados
├── infra/
│   ├── docker/                       ← api.Dockerfile, rpa.Dockerfile
│   ├── backup/                       ← restore.md, teste mensal de restauração
│   └── secrets/                      ← README apenas; arquivos reais ficam em DATA_DIR/secrets
├── tests/
│   ├── unit/
│   └── paridade/                     ← compara saída nova × CSVs/relatórios atuais (golden)
└── docs/
    ├── PLANO_ENGENHARIA.md           ← este documento
    ├── adr/                          ← decisões de arquitetura
    └── runbooks/

DATA_DIR  (ex.: C:\giraffas-erp-data — FORA do OneDrive/Google Drive)
├── entrada/<tenant>/<loja>/          ← arquivos brutos (equivalente a 01_entrada)
├── processados/
├── dashboards/                       ← HTML gerados por tenant
├── rpa_profiles/                     ← perfis de navegador (segredo)
├── logs/
├── backups/                          ← pg_dump diário/semanal/mensal
└── secrets/                          ← erp_master_key, postgres_password, n8n_encryption_key
```

**Regra de dependência:** `api → modules → core` · `pipelines → modules.*.service → core` · `automations → pipelines + core`. Nada importa de `api/`. É isso que permite, no futuro, separar um módulo em serviço próprio sem reescrever.

---

## 3. Modelo de dados: multi-tenant, RBAC e cofre de credenciais

DDL completo e comentado em [`database/sql/001_tenancy_rbac_credenciais.sql`](../database/sql/001_tenancy_rbac_credenciais.sql). Resumo:

### 3.1 Hierarquia de tenancy

```
redes (franqueadora: Giraffas)                ← white-label: marca, cores, domínio
  └── tenants (cliente pagante: Rodiza Alimentos)
        └── lojas (unidade: Shopping BH, sigla GSHBH, CNPJ)   ← tabela `lojas` do P2 + tenant_id
```

- Toda tabela de negócio tem `tenant_id` (obrigatório) e `loja_id` (quando aplicável).
- **Row-Level Security** no Postgres por `tenant_id`, como segunda barreira: mesmo que um endpoint esqueça o filtro, o banco não devolve dado de outro cliente. A aplicação faz `SET LOCAL app.tenant_id = ...` em cada request ou job.

### 3.2 RBAC (substitui o `papel_enum` gestor/auditor/colaborador)

| Papel | Escopo | Pode | Não pode |
|---|---|---|---|
| `plataforma_admin` | plataforma | tudo, incluindo criar tenants | — |
| `ti_ops` (TI / Operações) | plataforma ou tenant | saúde dos contêineres, logs, jobs (ver/reexecutar/cancelar), `rpa_erros`, backups | ver dado financeiro detalhado, ler credencial |
| `eng_dados` (Engenharia de Dados) | tenant | conexões de integração, **gravar/rotacionar** credenciais, parâmetros (taxas, prazos, de-para), disparar ingestão, conciliação | **ler** credencial em texto claro (ninguém lê, só o executor) |
| `franqueado_admin` | tenant | todos os dashboards de todas as lojas do tenant, gerir usuários do tenant | infraestrutura, credenciais |
| `gestor_loja` | loja | dashboards (DRE/Raio-X, Quebras, Indicadores, Metas, Desperdício) da própria loja, auditar despesas | outras lojas |
| `auditor` | loja | Raio-X: auditar, sugerir correção | alterar parâmetros |
| `colaborador` | loja | Raio-X: leitura + registrar nota | validar auditoria |

Mapeamento do legado: `gestor` → `franqueado_admin` + `ti_ops` (o dono hoje acumula), `auditor` → `auditor`, `colaborador` → `colaborador`.

Permissões são strings `modulo:acao` (`conciliacao:ler`, `credenciais:gravar`, `jobs:executar`, `logs:ler`…) ligadas aos papéis numa tabela. Um papel novo não exige deploy.

### 3.3 Integrações, parâmetros e credenciais

| Tabela | Para quê | Exemplo |
|---|---|---|
| `integracoes` (catálogo global) | Quais sistemas existem, que tipo de autenticação e que parâmetros exigem (JSON Schema) | `gcom` (senha, headful), `cielo_edi` (api_key), `cielo_email` (imap), `pluxee_portal` (senha + OTP e-mail + captcha manual), `sefaz_nfe` (certificado A1), `bradesco_cnab` (arquivo) |
| `conexoes` | Instância de uma integração **para um tenant/loja**, só com parâmetros **não secretos** | GCOM do tenant Rodiza: `{"empresa":"…","usuario":"…","unidade":"SHOPPING BH","rede":"GIRAFFAS"}` |
| `credenciais` | Segredos da conexão, **cifrados** | `password`, `api_key`, `client_secret`, `refresh_token`, `imap_app_password`, `certificado_pfx`, `certificado_senha` |
| `tenant_chaves` | Chave de dados (DEK) de cada tenant, cifrada pela chave-mestra | 1 ativa por tenant + históricas |
| `credencial_acessos` | Quem/qual job decifrou o quê, quando, para quê | trilha de auditoria (LGPD) |
| `parametros` | Parâmetro genérico por tenant/loja/módulo **com vigência** | `conciliacao.tolerancia_centavos`, `caixa.provisorio_ate_hora` |
| `taxas_prazos`, `depara_conciliacao`, `feriados`, `produtos_grupo` | Parâmetros estruturados que hoje são CSV no P1 | seeds a partir de `02_database/*.csv` |
| `branding` | White-label por rede/tenant | logo, cores, nome exibido, domínio |
| `jobs` | Fila e histórico de execução (pipelines e RPA) | status `manual_action_required` = o "exit 2" atual |

**Como a cifragem funciona (envelope encryption):**

```
Chave-mestra (KEK, 256 bits)  → arquivo em DATA_DIR/secrets/erp_master_key
                                montado como Docker secret SÓ em api e worker; nunca no banco, nunca no .env
   └── cifra → DEK por tenant  (tabela tenant_chaves, AES-256-GCM)
                  └── cifra → cada credencial (tabela credenciais, AES-256-GCM,
                              AAD = tenant_id|conexao_id|tipo — impede copiar o segredo de um cliente para outro)
```

- A API é **só escrita** para segredos: `PUT /conexoes/{id}/credenciais` aceita o valor e nunca o devolve. A leitura só retorna metadados: existe, versão, `fingerprint`, `expira_em`, `rotacionado_em`.
- Só o executor de jobs chama `vault.decifrar(...)`, e cada chamada grava `credencial_acessos` com `job_id`.
- Trocar a chave-mestra reembrulha só as DEKs (poucas linhas). As credenciais não são recifradas.
- Evolução natural, se um cliente exigir: trocar `core/security/vault.py` por HashiCorp Vault ou Infisical, com a mesma interface.

Esboço ORM (SQLAlchemy 2, mesmo estilo do P2):

```python
class Conexao(Base):
    __tablename__ = "conexoes"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    loja_id: Mapped[int | None] = mapped_column(ForeignKey("lojas.id"))
    integracao_id: Mapped[int] = mapped_column(ForeignKey("integracoes.id"))
    nome: Mapped[str] = mapped_column(String(120))
    parametros: Mapped[dict] = mapped_column(JSONB, default=dict)   # NÃO secretos
    ativo: Mapped[bool] = mapped_column(default=True)
    ultimo_sucesso_em: Mapped[datetime | None]

class Credencial(Base):
    __tablename__ = "credenciais"
    __table_args__ = (UniqueConstraint("conexao_id", "tipo", "versao"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    conexao_id: Mapped[int] = mapped_column(ForeignKey("conexoes.id", ondelete="CASCADE"))
    tipo: Mapped[str] = mapped_column(String(40))          # password | api_key | certificado_pfx ...
    versao: Mapped[int] = mapped_column(default=1)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)       # 12 bytes, único por cifragem
    dek_versao: Mapped[int]
    fingerprint: Mapped[str] = mapped_column(String(64))    # HMAC do valor — detecta troca sem revelar
    ativo: Mapped[bool] = mapped_column(default=True)
    expira_em: Mapped[datetime | None]
```

```python
# core/security/vault.py — núcleo (cryptography.hazmat.primitives.ciphers.aead.AESGCM)
def cifrar(tenant_id, conexao_id, tipo, valor: bytes) -> tuple[bytes, bytes, int]:
    dek, dek_versao = _dek_ativa(tenant_id)                 # decifrada com a KEK, cache curto em memória
    nonce = os.urandom(12)
    aad = f"{tenant_id}|{conexao_id}|{tipo}".encode()
    return AESGCM(dek).encrypt(nonce, valor, aad), nonce, dek_versao
```

**Adaptador para os conectores atuais (mudança mínima):** as chamadas `keyring.get_password(CRED_TARGET, USER)` passam a ser `credenciais.obter(conexao, "password")`. A implementação `KeyringProvider` continua existindo para rodar do jeito antigo durante a transição, e `VaultProvider` é a nova. A escolha é por variável de ambiente, e a lógica do conector não muda.

---

## 4. `docker-compose.yml` unificado

Entregue em [`docker-compose.yml`](../docker-compose.yml) + [`.env.example`](../.env.example) + [`database/init/00_criar_bancos.sh`](../database/init/00_criar_bancos.sh).

| Serviço | Papel | Porta (só `127.0.0.1`) | Persistência |
|---|---|---|---|
| `postgres` | Banco único, com os bancos `erp` e `n8n` | 55433 | volume nomeado `pgdata` |
| `api` | FastAPI: REST + dashboards HTML atrás de login + Raio-X | 8100 | `DATA_DIR/dashboards`, `entrada` |
| `worker` | Executa jobs **sem navegador** (pipelines, IMAP Cielo, cargas) | — | `DATA_DIR/entrada`, `processados`, `logs` |
| `console` | Streamlit: console de TI / Eng. de Dados (jobs, logs, conexões, parâmetros) | 8501 | — |
| `n8n` | Agendamento (substitui o Agendador do Windows) + alertas + integrações simples | 5678 | volume `n8n_data` + banco `n8n` |
| `backup` | `pg_dump` diário/semanal/mensal com retenção | — | `DATA_DIR/backups` |
| `autoheal` | Reinicia contêiner que ficou *unhealthy* (`restart: always` sozinho só cobre queda) | — | — |
| `rpa` *(perfil `rpa`)* | **Experimento:** Chrome headful em Xvfb + noVNC para captcha humano | 6080 | `DATA_DIR/rpa_profiles` |
| `cloudflared` *(perfil `publico`)* | Túnel Cloudflare + Access: acesso pelo celular sem abrir porta no roteador | — | — |

Decisões:
- **`restart: always` em tudo**, healthchecks reais e `depends_on: condition: service_healthy`, rotação de log (`max-size`) para o disco não encher.
- **Postgres em volume nomeado, não em pasta mapeada.** No Windows, pasta mapeada passa por uma camada de compartilhamento de arquivos que é lenta e arriscada para banco vivo. Tudo que é para humano ver ou copiar (backups, arquivos de entrada, dashboards gerados, logs) fica em **pastas mapeadas em `DATA_DIR`, fora do OneDrive**, e o **backup** é a garantia de durabilidade do banco.
- **Portas diferentes das atuais** (8100/55433 contra 8000/55432) para os dois sistemas rodarem **lado a lado** durante a transição.
- **Segredos como Docker secrets** (arquivos em `DATA_DIR/secrets`), montados só nos serviços que precisam.
- **Backup 3-2-1:** o diário fica em `DATA_DIR/backups`, uma cópia cifrada vai para fora da máquina (Google Drive ou armazenamento de objetos, via rclone no n8n ou tarefa do host), e um **teste de restauração mensal** fica documentado em `infra/backup/`.

**Sobre 24x7 "de verdade":** `restart: always` só funciona se o Docker estiver de pé. Num Windows de uso pessoal isso significa Docker Desktop iniciando no login, login automático, suspensão desligada e nobreak. A recomendação para produção é um **host dedicado** (mini-PC com Linux + Docker Engine, ou uma VPS). O compose é o mesmo nos dois casos. O executor RPA com navegador é a única peça que fica no Windows até o experimento do perfil `rpa` provar que funciona.

---

## 5. Plano de implementação em fases (sem parar a loja)

Estratégia **strangler fig**: o sistema novo roda **em sombra**, lendo as mesmas entradas, até provar paridade. Só então cada peça antiga é desligada, **uma de cada vez**, sempre com volta atrás.

> **Regra de ouro:** durante todas as fases, `executar_tudo.bat`, a tarefa agendada, o site atual e o Raio-X em `localhost:8000` **continuam sendo a fonte de verdade**, até o corte de cada módulo.

### Fase 0: Preparação (≈1 semana) · risco zero
- [x] ~~Decidir o host 24x7~~. **Decidido (28/09): construir e validar no PC local e depois transferir para a nuvem (Fase 5B).**
- [ ] Criar `DATA_DIR` fora de OneDrive e Google Drive (ex.: `C:\giraffas-erp-data`).
- [ ] `git init` neste repositório, `.gitignore`, repositório remoto privado.
- [ ] **Congelar o dataset de referência:** cópia somente leitura de `02_database/*.csv` + `pg_dump` do Raio-X → `DATA_DIR/golden/2026-09-28/`.
- [x] Confirmar se `giraffas-dash.pages.dev` está público. **Confirmado em 28/09: PÚBLICO.** Os 6 dashboards + menu respondem HTTP 200 sem login.
- [ ] Pôr Cloudflare Access (Zero Trust → Applications → self-hosted, domínio `giraffas-dash.pages.dev` **e** `*.giraffas-dash.pages.dev`) na frente **já**, independentemente deste plano. Não exige mudar código do Datalake.
- [ ] Fechar as pendências de escrita no GCOM abertas no STATUS do Raio-X **antes** de mexer em qualquer coisa que fale com o GCOM.

### Fase 1: Fundação (≈2 semanas) · sistema atual intocado
- [ ] Criar `core/`, `api/` e `database/` a partir do código do P2 (cópia, não movimentação), mais `pyproject.toml` e Dockerfiles.
- [ ] Migrações novas: `redes`, `tenants`, `lojas.tenant_id`, RBAC, `integracoes`, `conexoes`, `credenciais`, `tenant_chaves`, `jobs`, `parametros`.
- [ ] `docker compose up -d` (postgres, api, n8n, backup, autoheal) nas portas novas.
- [ ] Restaurar o `pg_dump` do Raio-X no banco `erp`, rodar as migrações novas e criar o tenant "Rodiza" e a loja "Shopping BH" a partir do registro existente.
- **Aceite:** o Raio-X novo (`:8100`) mostra os mesmos 7 meses e os mesmos totais por mês da tabela de conferência do STATUS do P2. Primeiro backup automático gerado e **restaurado com sucesso** num banco descartável.
- **Volta atrás:** `docker compose down`. Nada do antigo foi tocado.

### Fase 1B: Primeiro módulo novo — Conciliação de Pagamentos 3 vias (≈3 semanas, junto com a Fase 2)
Nasce **direto no IN-360** (não no Raio-X antigo), em cima da base restaurada na Fase 1. Detalhe na seção 6.

### Fase 2: Pipelines em sombra (≈3–4 semanas) · o antigo continua publicando
- [ ] Portar `conciliacao_fontes/` (sem mudar lógica) e separar cada `pipeline_*.py` em parse / regra / I/O.
- [ ] Montar a pasta original `01_entrada` **em modo somente leitura** (`:ro`) no `worker`, para o sistema novo consumir exatamente os mesmos arquivos sem tocar no original.
- [ ] Carregar o histórico dos CSVs e os seeds de parâmetros.
- [ ] **Testes de paridade diários** (`tests/paridade/`), comparando por chave (data, filial, fonte, categoria, bandeira) com tolerância de R$0,01: ABS/Realizado → Quebra → Metas → Desperdício → Conciliação C2 → C3 → Central.
- [ ] n8n agenda a rodada em sombra **depois** das 07:00 do legado e envia o relatório de divergências.
- **Aceite por módulo:** 14 dias seguidos com divergência zero (ou só divergências explicadas e documentadas).

### Fase 3: Cofre + automações (≈3 semanas) · um conector por vez
- [ ] `importar_keyring.py`: você roda uma vez, na sua máquina, e as credenciais vão do keyring para o cofre (nunca passam por chat nem por arquivo).
- [ ] `CredentialProvider` nos conectores (Keyring primeiro, Vault depois).
- [ ] Ordem, da menor para a maior dependência de navegador: **Cielo e-mail/IMAP** (em contêiner) → **GCOM delta** (host agent Windows) → Desperdício → despesas DRE → Alelo/Pluxee/Ticket/VR (assistidos, com status `manual_action_required` e alerta).
- [ ] Experimento do perfil `rpa` (Xvfb + noVNC) **só com GCOM de leitura**. Se o WAF bloquear, o host agent continua sendo a solução definitiva, e a decisão fica registrada em ADR.
- **Corte por conector:** após 14 dias de sucesso em sombra, desativar **só aquela** etapa no `.bat`/tarefa antiga.
- **Volta atrás:** reativar a etapa antiga. As credenciais continuam no keyring durante toda a fase.

### Fase 4: Dashboards atrás de login (≈2 semanas)
- [ ] API serve os mesmos HTML (templates do P1) com dados da loja do usuário, e o menu central é gerado por tenant.
- [ ] Cloudflare Tunnel + Access (perfil `publico`) substitui o Cloudflare Pages público.
- [ ] Log de acesso por usuário (pedido já registrado no STATUS do P1: quem, quanto tempo, o que abriu) sai do `audit_log`.
- **Corte:** novo link no celular. O site antigo fica como leitura por 30 dias e depois é desligado.

### Fase 5: Corte final (≈1 semana)
- [ ] Todos os módulos com 14 dias verdes. Desativar a tarefa `GIRAFFAS_Atualizacao_Diaria` e o Raio-X antigo.
- [ ] Pastas originais viram **arquivo somente leitura** por 60 dias. **Não apagar.**
- [ ] Runbooks de TI: subir/derrubar, restaurar backup, trocar a chave-mestra, captcha pendente.

### Fase 5B: Transferência para a nuvem 24x7 (≈1–2 semanas, depois do corte local estável)
Decisão de 28/09: tudo é construído e validado **no PC local** (Fases 1–5), e só depois o mesmo compose sobe numa VPS.
- [ ] Contratar a VPS (Linux + Docker Engine, região Brasil) e subir o mesmo `docker-compose.yml` com o mesmo `.env` (só muda `DATA_DIR`) e **segredos novos** de produção (a chave-mestra do cofre é migrada, não recriada, senão as credenciais se perdem).
- [ ] Migrar dados: `pg_dump` local → `pg_restore` na VPS, e ensaiar antes num banco descartável.
- [ ] Acesso externo via perfil `publico` (Cloudflare Tunnel + Access). Nenhuma porta aberta na VPS além de SSH.
- [ ] **Automações com navegador continuam no PC local** (host agent consumindo a fila da API na nuvem pelo túnel), a não ser que o experimento do perfil `rpa` tenha dado certo. Com isso o PC deixa de ser crítico para dashboards/API e só importa para as extrações do GCOM e dos portais.
- [ ] Backup da VPS com cópia fora do provedor. Teste de restauração repetido na nuvem.
- **Volta atrás:** o stack local continua íntegro por 30 dias, e reapontar o túnel devolve o tráfego para ele.

### Fase 6: Produto multi-tenant (contínuo)
- [ ] Onboarding de loja nova: cadastro do tenant → conexões → credenciais (tela da Eng. de Dados) → seeds de parâmetros → primeira carga → dashboards.
- [ ] Testes automatizados de isolamento (usuário do tenant A nunca vê B, validado também via RLS).
- [ ] White-label (`branding`), LGPD (base legal, retenção, exportação/exclusão por tenant), métricas por tenant (jobs, falhas, uso).
- [ ] Integrações "limpas" que reduzem o RPA: Cielo EDI (contato já registrado no STATUS do P1), extrato bancário CNAB/Open Finance, relatórios agendados por e-mail dos portais.

### Riscos principais e mitigação

| Risco | Mitigação |
|---|---|
| WAF do GCOM bloqueia navegador em contêiner | Host agent Windows é o caminho padrão. O contêiner é experimento |
| Captcha dos portais de voucher em execução sem ninguém na máquina | Status `manual_action_required` + alerta n8n + login assistido periódico (política atual do P1) |
| Divergência silenciosa na portabilidade dos pipelines | Testes de paridade com dataset de referência, corte por módulo |
| Perda do banco | Volume nomeado + pg_dump diário + cópia fora da máquina + restauração testada mensalmente |
| Vazamento entre clientes | `tenant_id` obrigatório + RLS + testes de isolamento + credenciais com AAD por tenant |
| Chave-mestra perdida = credenciais irrecuperáveis | Cópia offline da chave (cofre de senhas pessoal + papel em local seguro), procedimento de rotação documentado |

---

## 6. Módulo novo: Conciliação de Pagamentos 3 vias (pedido ↔ banco ↔ DRE)

**Objetivo:** fechar o que está lançado no DRE (despesas do GCOM/Raio-X) contra o que realmente saiu
da conta (débitos do extrato) e contra o pedido de origem. Cada match fica **guardado com status**, e
nada é reprocessado do zero a cada rodada. As regras de pagamento de cada fornecedor passam a ser dado
reaproveitável, não script.

**Por que nasce aqui e não no Raio-X antigo:** construir no Raio-X exigiria portar depois. Aqui ele já
nasce com tenant, RBAC e cofre, e **resolve uma duplicidade**: hoje o extrato Bradesco entra por dois
caminhos (Datalake lê só os créditos para a Camada 3, e a planilha `15_Bradesco_tratado_*.xlsx` + o
script de atualização tratam créditos e débitos). No IN-360 o extrato é importado **uma vez** (módulo
`banco`): débitos alimentam esta conciliação, créditos alimentam a conciliação de recebíveis.

**Modelo de dados:** [`database/sql/002_conciliacao_pagamentos.sql`](../database/sql/002_conciliacao_pagamentos.sql)
(testado em Postgres 16: um débito pagando 2 despesas calcula a diferença, e o mesmo débito em 2
conciliações é bloqueado pelo banco).

| Tabela | Papel |
|---|---|
| `contas_bancarias`, `extrato_importacoes`, `extrato_lancamentos` | Importação idempotente (hash do arquivo + chave conta/data/histórico/valor/ocorrência, **sem** depender do Dcto., que o banco reemite) |
| `fornecedores`, `extrato_regras_fornecedor` | Como o texto do extrato vira fornecedor, semeado a partir das colunas Classificação/Fornecedor da planilha tratada |
| `padroes_pagamento` | Regra por fornecedor, com vigência: `um_para_um` (RFG), `consolidado_mensal` (Kelminas), `agrupado_vencimento` (Ribeiro), `nota_mais_ajuste` (JM), `livre` |
| `conciliacoes` + `conciliacao_itens` | O match (N:M com `valor_alocado`), status `batido / sugerido / pendente / investigar / descartado`, diferença calculada, quem confirmou |

**Motor de match (por fornecedor, conforme o padrão vigente):**
1. `um_para_um`: 1 débito ↔ 1 despesa, valor exato (± tolerância) na janela do vencimento/pagamento.
2. `consolidado_mensal`: 1 débito ↔ todas as despesas da competência do fornecedor, soma exata.
3. `agrupado_vencimento`: 1 débito ↔ despesas com o mesmo vencimento, soma exata.
4. `nota_mais_ajuste`: 1 débito ↔ nota (+ despesa de ajuste), diferença dentro de `ajuste_max_pct`, e **sempre vai para humano**.
5. Sobra sem par: `pendente` (débito sem despesa = possível lançamento faltando no GCOM; despesa sem débito = possível não pago ou pago por outra conta).

Regra de status: só vira `batido` sozinho o match **exato** de padrão 1–3. Todo o resto é `sugerido`
e segue o mesmo fluxo da auditoria de classificação (humano confirma, `audit_log` registra). **Nada
escreve no GCOM.**

**Reaproveitamento:** parser `banco_bradesco.py` do Datalake (formatos CSV/XLSX/tratado, sem o filtro
"só crédito", com a lógica original intocada), a checagem de saldo corrido e o aprendizado por
`LEFT(histórico,33)` de `atualiza_bradesco_jul_ago_2026.py`, `despesas` + `sub_itens` +
`data_pagamento` do Raio-X, e o padrão de tela da auditoria.

**Entregas (em ordem):**
1. Importar extrato Bradesco (tela de upload + job) e semear fornecedores/regras a partir da planilha tratada.
2. Cadastro de padrões de pagamento (os 4 fornecedores conhecidos).
3. Motor de match + tela "Conciliação" por competência: débitos × despesas, filtro por status, confirmar/descartar/investigar.
4. Fechamento do mês: totais batido × pendente por fornecedor e por linha do DRE.
5. Via "pedido" = **lançamento PREVISTO no GCOM** (decisão 28/09: a planilha de pedidos deixa de existir).
   O extrator de despesas passa a trazer também PREVISTO / REAL EM ABERTO / A VENCER / VENCIDO (hoje só
   traz PAGO), guardando cada mudança de status em `despesa_status_historico`. O DRE (`vw_despesas_dre`)
   ignora PREVISTO para não contar duas vezes, e `vw_previsoes_abertas` mostra pedidos ainda sem lançamento real.

**Critério de aceite:** reproduzir o resultado da última rodada manual (mesmos pares e mesmas pendências)
para os meses já conciliados, e divergência só com explicação registrada.

**Pendências para começar:**
- ~~O que é o "pedido"~~ **Definido:** previsão lançada no GCOM. Falta confirmar no GCOM ao vivo: ao efetivar a previsão, o GCOM **muda o status do mesmo documento** ou **cria um documento novo**? (o modelo cobre os dois casos via `despesas.previsao_id`). E em qual tela as previsões aparecem para extração (DRE Interativo filtra só pago?).
- Os resultados/scripts da última rodada manual (servem de gabarito de aceite).
- Os padrões dos 4 fornecedores confirmados e, se houver, de outros.
