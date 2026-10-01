from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from core.db import Base


class AuditLog(Base):
    """Quem mudou o quê, quando (tabela herdada do Raio-X + tenant/ip)."""
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    acao: Mapped[str] = mapped_column(String(120))
    entidade: Mapped[str] = mapped_column(String(60))
    entidade_id: Mapped[int | None] = mapped_column(nullable=True)
    detalhes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


def registrar(db: Session, acao: str, entidade: str, entidade_id: int | None = None, *,
              usuario_id: int | None = None, tenant_id: int | None = None,
              detalhes: dict | None = None, ip: str | None = None) -> None:
    """Adiciona à sessão; quem chama faz o commit junto com a operação auditada.
    Nunca passar segredo em `detalhes`."""
    db.add(AuditLog(acao=acao, entidade=entidade, entidade_id=entidade_id, usuario_id=usuario_id,
                    tenant_id=tenant_id, detalhes=detalhes, ip=ip))
