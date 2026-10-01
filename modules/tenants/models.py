from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import Base


class Rede(Base):
    """Franqueadora (ex.: Giraffas) — base do white-label."""
    __tablename__ = "redes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    codigo: Mapped[str] = mapped_column(Text, unique=True)
    nome: Mapped[str] = mapped_column(Text)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Tenant(Base):
    """Cliente pagante (empresa franqueada, ex.: Rodiza Alimentos)."""
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rede_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("redes.id"))
    codigo: Mapped[str] = mapped_column(Text, unique=True)
    razao_social: Mapped[str] = mapped_column(Text)
    cnpj: Mapped[str | None] = mapped_column(String(14), nullable=True)
    status: Mapped[str] = mapped_column(Text, default="ativo")
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Loja(Base):
    """Unidade. Tabela herdada do Raio-X + tenant_id / filial_sigla / ativo."""
    __tablename__ = "lojas"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    razao_social: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cnpj: Mapped[str | None] = mapped_column(String(20), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=True)
    filial_sigla: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)

    despesas: Mapped[list["Despesa"]] = relationship(back_populates="loja")  # noqa: F821
