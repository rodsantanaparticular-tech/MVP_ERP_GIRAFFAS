from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Computed, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base

STATUS = ("batido", "sugerido", "pendente", "investigar", "descartado")


class Conciliacao(Base):
    """Um match: débito(s) do extrato ↔ documento(s) do GCOM. Ver modules/conciliacao/motor.py."""
    __tablename__ = "conciliacoes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"))
    competencia: Mapped[str] = mapped_column(String(7))
    status: Mapped[str] = mapped_column(Text)
    padrao_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("padroes_pagamento.id"), nullable=True)
    regra_aplicada: Mapped[str] = mapped_column(Text)
    total_extrato: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total_despesas: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    diferenca: Mapped[Decimal] = mapped_column(Numeric(14, 2), Computed("total_extrato - total_despesas"))
    acrescimo: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    nota: Mapped[str | None] = mapped_column(Text, nullable=True)
    criado_por: Mapped[str] = mapped_column(Text)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    confirmado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConciliacaoItem(Base):
    __tablename__ = "conciliacao_itens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"))
    conciliacao_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("conciliacoes.id", ondelete="CASCADE"))
    tipo: Mapped[str] = mapped_column(Text)
    extrato_lancamento_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("extrato_lancamentos.id"),
                                                              nullable=True)
    despesa_id: Mapped[int | None] = mapped_column(ForeignKey("despesas.id"), nullable=True)
    valor_alocado: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
