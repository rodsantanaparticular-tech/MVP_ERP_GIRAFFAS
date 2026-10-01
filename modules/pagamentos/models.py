from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import ARRAY, BigInteger, Boolean, Date, DateTime, ForeignKey, Numeric, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base

TIPOS_PADRAO = ("um_para_um", "consolidado_mensal", "agrupado_vencimento", "nota_mais_ajuste", "livre")


class Fornecedor(Base):
    """CRM de fornecedores do cliente (antes: CRM_Fornecedores_Rodiza.xlsx)."""
    __tablename__ = "fornecedores"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"))
    nome: Mapped[str] = mapped_column(Text)
    razao_social: Mapped[str | None] = mapped_column(Text, nullable=True)
    cnpj: Mapped[str | None] = mapped_column(String(14), nullable=True)
    categoria: Mapped[str | None] = mapped_column(Text, nullable=True)
    apelidos: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    prazo_pagamento: Mapped[str | None] = mapped_column(Text, nullable=True)
    endereco: Mapped[str | None] = mapped_column(Text, nullable=True)
    observacoes: Mapped[str | None] = mapped_column(Text, nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                    onupdate=func.now())
    atualizado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)


class PadraoPagamento(Base):
    """Como o fornecedor costuma ser pago. Um vigente por vez (vigencia_fim NULL)."""
    __tablename__ = "padroes_pagamento"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"))
    fornecedor_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fornecedores.id"))
    tipo: Mapped[str] = mapped_column(Text)
    janela_dias_antes: Mapped[int] = mapped_column(SmallInteger, default=3)
    janela_dias_depois: Mapped[int] = mapped_column(SmallInteger, default=5)
    tolerancia_valor: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    ajuste_max_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    parametros: Mapped[dict] = mapped_column(JSONB, default=dict)
    vigencia_inicio: Mapped[date] = mapped_column(Date, server_default=func.current_date())
    vigencia_fim: Mapped[date | None] = mapped_column(Date, nullable=True)
    observacao: Mapped[str | None] = mapped_column(Text, nullable=True)
    atualizado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DespesaRecorrente(Base):
    """Saída esperada todo mês (as "despesas fixas" do CRM): dia e faixa de valor."""
    __tablename__ = "despesas_recorrentes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"))
    fornecedor_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fornecedores.id"), nullable=True)
    descricao: Mapped[str] = mapped_column(Text)
    dia_inicio: Mapped[int] = mapped_column(SmallInteger)
    dia_fim: Mapped[int] = mapped_column(SmallInteger)
    valor_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    valor_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    valor_variavel: Mapped[bool] = mapped_column(Boolean, default=False)
    vigencia_fim: Mapped[date | None] = mapped_column(Date, nullable=True)
    observacao: Mapped[str | None] = mapped_column(Text, nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    atualizado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                    onupdate=func.now())
