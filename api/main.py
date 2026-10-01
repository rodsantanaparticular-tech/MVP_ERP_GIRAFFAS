from fastapi import FastAPI
from sqlalchemy import text

import modules.models  # noqa: F401 -- registra todos os modelos
from core.db import nova_sessao
from modules.banco.router import router as banco
from modules.identity.router import router as identidade
from modules.integrations.router import router as integracoes
from modules.pagamentos.router import router as pagamentos
from modules.paineis.router import router as paineis
from modules.tenants.router import router as tenants

app = FastAPI(title="ERP IN-360 — API", version="0.1.0",
              description="Etapa 1: perfis de acesso (RBAC), clientes/lojas e cofre de senhas. Fase 1B: CRM de fornecedores e padrões de pagamento. Painéis em /painel (fornecedores) e /painel/banco (banco e caixa).")

app.include_router(identidade)
app.include_router(tenants)
app.include_router(integracoes)
app.include_router(pagamentos)
app.include_router(paineis)
app.include_router(banco)


@app.get("/health", tags=["operação"])
def health():
    with nova_sessao() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok"}
