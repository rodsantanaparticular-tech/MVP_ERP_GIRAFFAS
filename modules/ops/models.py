from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base


class RpaErro(Base):
    """Falha reportada por script de extração (herdado do Raio-X + tenant_id)."""
    __tablename__ = "rpa_erros"

    id: Mapped[int] = mapped_column(primary_key=True)
    fonte: Mapped[str] = mapped_column(String(60))
    mes: Mapped[str | None] = mapped_column(String(7), nullable=True)
    etapa: Mapped[str | None] = mapped_column(String(120), nullable=True)
    mensagem: Mapped[str] = mapped_column(Text)
    screenshot: Mapped[str | None] = mapped_column(String(255), nullable=True)

    resolvido: Mapped[bool] = mapped_column(Boolean, default=False)
    resolvido_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolvido_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=True)
