from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base


class RealizadoDia(Base):
    """Faturamento de um dia numa loja (espelho de database_realizado_dia.csv da Gestão)."""
    __tablename__ = "vendas_realizado_dia"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"))
    loja_id: Mapped[int] = mapped_column(ForeignKey("lojas.id"))
    data: Mapped[date] = mapped_column(Date)
    faturamento: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    tc: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tm: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    adc: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    beb: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    sob: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    origem: Mapped[str | None] = mapped_column(Text, nullable=True)
    fonte: Mapped[str] = mapped_column(Text, default="gestao_realizado_dia")
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                    onupdate=func.now())
