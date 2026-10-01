from functools import lru_cache

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from core.config import settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine():
    return create_engine(settings.database_url, pool_pre_ping=True)


SessionLocal = sessionmaker(autocommit=False, autoflush=False)


def nova_sessao() -> Session:
    return SessionLocal(bind=get_engine())


def get_db():
    db = nova_sessao()
    try:
        yield db
    finally:
        db.close()


# --- Isolamento por tenant (Row-Level Security) -------------------------------
# O tenant fica em session.info e é reaplicado no início de CADA transação como
# configuração local (set_config(..., true)): some sozinho no commit/rollback e
# nunca vaza para outra requisição que reutilize a mesma conexão do pool.

@event.listens_for(Session, "after_begin")
def _aplica_tenant(session, transaction, connection):
    tenant_id = session.info.get("tenant_id")
    if tenant_id is not None:
        connection.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})


def usar_tenant(db: Session, tenant_id: int) -> None:
    db.info["tenant_id"] = tenant_id
    if db.in_transaction():
        db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
