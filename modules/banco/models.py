from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import ARRAY, BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base


class ContaBancaria(Base):
    __tablename__ = "contas_bancarias"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"))
    loja_id: Mapped[int | None] = mapped_column(ForeignKey("lojas.id"), nullable=True)
    banco: Mapped[str] = mapped_column(Text)
    agencia: Mapped[str | None] = mapped_column(Text, nullable=True)
    conta: Mapped[str | None] = mapped_column(Text, nullable=True)
    apelido: Mapped[str] = mapped_column(Text)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)


class ExtratoImportacao(Base):
    __tablename__ = "extrato_importacoes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"))
    conta_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("contas_bancarias.id"))
    arquivo_nome: Mapped[str] = mapped_column(Text)
    arquivo_sha256: Mapped[str] = mapped_column(String(64))
    formato: Mapped[str] = mapped_column(Text)
    periodo_de: Mapped[date | None] = mapped_column(Date, nullable=True)
    periodo_ate: Mapped[date | None] = mapped_column(Date, nullable=True)
    linhas_lidas: Mapped[int] = mapped_column(Integer, default=0)
    linhas_novas: Mapped[int] = mapped_column(Integer, default=0)
    saldo_inicial: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    saldo_final: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    quebras_saldo: Mapped[int] = mapped_column(Integer, default=0)
    saldo_confere: Mapped[bool] = mapped_column(Boolean)
    importado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    importado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExtratoLancamento(Base):
    __tablename__ = "extrato_lancamentos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"))
    conta_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("contas_bancarias.id"))
    importacao_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("extrato_importacoes.id"))
    data: Mapped[date] = mapped_column(Date)
    ordem: Mapped[int] = mapped_column(Integer)
    historico: Mapped[str] = mapped_column(Text)
    historico_chave: Mapped[str] = mapped_column(Text)
    documento: Mapped[str | None] = mapped_column(Text, nullable=True)
    valor: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    natureza: Mapped[str] = mapped_column(String(1))
    saldo_informado: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    ocorrencia: Mapped[int] = mapped_column(SmallInteger, default=1)
    fornecedor_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fornecedores.id"), nullable=True)
    classificacao: Mapped[str | None] = mapped_column(Text, nullable=True)
    classificacao_origem: Mapped[str | None] = mapped_column(Text, nullable=True)
    favorecido: Mapped[str | None] = mapped_column(Text, nullable=True)
    regra_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("extrato_regras.id"), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExtratoRegra(Base):
    """Como o texto do extrato vira favorecido (e, quando o texto decide, a classificação)."""
    __tablename__ = "extrato_regras"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"))
    padrao_texto: Mapped[str] = mapped_column(Text)
    tipo_match: Mapped[str] = mapped_column(Text, default="prefixo")
    natureza: Mapped[str] = mapped_column(String(1))
    favorecido: Mapped[str] = mapped_column(Text)
    fornecedor_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fornecedores.id"), nullable=True)
    classificacao: Mapped[str | None] = mapped_column(Text, nullable=True)
    classificacoes: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    parametros: Mapped[dict] = mapped_column(JSONB, default=dict)
    origem: Mapped[str] = mapped_column(Text)
    ocorrencias: Mapped[int] = mapped_column(Integer, default=0)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    atualizado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                    onupdate=func.now())


GRUPOS_CATEGORIA = ("despesa", "receita", "fora_dre", "outra_entrada")


class ExtratoCategoria(Base):
    """Classe do extrato → categoria do DRE (Tipo de Desembolso do GCOM). favorecido NULL = qualquer um."""
    __tablename__ = "extrato_categorias"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"))
    natureza: Mapped[str] = mapped_column(String(1))
    classificacao: Mapped[str] = mapped_column(Text)
    favorecido: Mapped[str | None] = mapped_column(Text, nullable=True)
    categoria: Mapped[str] = mapped_column(Text)
    grupo: Mapped[str] = mapped_column(Text)
    atualizado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                    onupdate=func.now())
