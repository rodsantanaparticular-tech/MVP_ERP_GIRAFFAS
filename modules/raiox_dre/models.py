"""Modelos do Raio-X do DRE — copiados do Raio-X (in-360-giraffas/app/models.py)
sem mudança de regra. Rotas e tela entram na etapa do módulo Raio-X."""
import enum
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Enum, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import Base


class OrigemDespesa(str, enum.Enum):
    gcom = "gcom"
    manual = "manual"


class StatusAuditoria(str, enum.Enum):
    pendente = "pendente"
    ok = "ok"
    revisar = "revisar"
    errado = "errado"


class Despesa(Base):
    __tablename__ = "despesas"
    __table_args__ = (UniqueConstraint("loja_id", "mes", "id_original", name="uq_despesa_origem"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    loja_id: Mapped[int] = mapped_column(ForeignKey("lojas.id"))
    mes: Mapped[str] = mapped_column(String(7), index=True)
    id_original: Mapped[int | None] = mapped_column(nullable=True)

    doc: Mapped[str] = mapped_column(String(60))
    valor: Mapped[float] = mapped_column(Numeric(12, 2))
    venc: Mapped[date] = mapped_column(Date)
    entrada: Mapped[date] = mapped_column(Date)
    fornecedor: Mapped[str] = mapped_column(String(200))
    desembolso: Mapped[str] = mapped_column(String(120))
    sub: Mapped[str] = mapped_column(String(120))
    status_gcom: Mapped[str] = mapped_column(String(40))
    origem: Mapped[OrigemDespesa] = mapped_column(Enum(OrigemDespesa, name="origem_enum"), default=OrigemDespesa.gcom)

    observacoes_gcom: Mapped[str | None] = mapped_column(Text, nullable=True)
    observacoes_lida_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    data_pagamento: Mapped[date | None] = mapped_column(Date, nullable=True)
    sub_itens: Mapped[list | None] = mapped_column(JSON, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    loja: Mapped["Loja"] = relationship(back_populates="despesas")  # noqa: F821
    auditoria: Mapped["Auditoria"] = relationship(back_populates="despesa", uselist=False,
                                                  cascade="all, delete-orphan")


class Auditoria(Base):
    __tablename__ = "auditorias"

    id: Mapped[int] = mapped_column(primary_key=True)
    despesa_id: Mapped[int] = mapped_column(ForeignKey("despesas.id"), unique=True)

    status: Mapped[StatusAuditoria] = mapped_column(Enum(StatusAuditoria, name="status_enum"),
                                                    default=StatusAuditoria.pendente)
    corr_tipo: Mapped[str | None] = mapped_column(String(120), nullable=True)
    corr_sub: Mapped[str | None] = mapped_column(String(120), nullable=True)
    nota: Mapped[str | None] = mapped_column(Text, nullable=True)
    validacao: Mapped[str | None] = mapped_column(String(30), nullable=True)

    excluido: Mapped[bool] = mapped_column(Boolean, default=False)
    excluido_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    synced_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    atualizado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)

    despesa: Mapped["Despesa"] = relationship(back_populates="auditoria")


class RegraClassificacao(Base):
    __tablename__ = "regras_classificacao"

    id: Mapped[int] = mapped_column(primary_key=True)
    errado: Mapped[str] = mapped_column(Text)
    correto: Mapped[str] = mapped_column(Text)
    criterio: Mapped[str | None] = mapped_column(Text, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    criado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)


class SyncSession(Base):
    __tablename__ = "sync_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    loja_id: Mapped[int] = mapped_column(ForeignKey("lojas.id"))
    mes: Mapped[str] = mapped_column(String(7))
    status: Mapped[str] = mapped_column(String(30))
    qtd_itens: Mapped[int] = mapped_column(default=0)
    solicitado_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    logado_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    encerrado_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
