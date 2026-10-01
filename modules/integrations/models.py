from datetime import datetime

from sqlalchemy import (ARRAY, BigInteger, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text,
                        UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base


class Integracao(Base):
    """Catálogo global de sistemas externos (GCOM, Cielo, Alelo, bancos, SEFAZ...)."""
    __tablename__ = "integracoes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    codigo: Mapped[str] = mapped_column(Text, unique=True)
    nome: Mapped[str] = mapped_column(Text)
    categoria: Mapped[str] = mapped_column(Text)
    tipo_auth: Mapped[str] = mapped_column(Text)
    requer_navegador: Mapped[bool] = mapped_column(Boolean, default=False)
    requer_humano: Mapped[bool] = mapped_column(Boolean, default=False)
    schema_parametros: Mapped[dict] = mapped_column(JSONB, default=dict)
    segredos_exigidos: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)


class Conexao(Base):
    """Uma integração configurada para um cliente/loja. `parametros` = só dados NÃO secretos."""
    __tablename__ = "conexoes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), index=True)
    loja_id: Mapped[int | None] = mapped_column(ForeignKey("lojas.id"), nullable=True)
    integracao_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("integracoes.id"))
    nome: Mapped[str] = mapped_column(Text)
    parametros: Mapped[dict] = mapped_column(JSONB, default=dict)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    ultimo_teste_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ultimo_sucesso_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ultimo_erro: Mapped[str | None] = mapped_column(Text, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantChave(Base):
    __tablename__ = "tenant_chaves"
    __table_args__ = (UniqueConstraint("tenant_id", "versao"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"))
    versao: Mapped[int] = mapped_column(Integer)
    dek_cifrada: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    kek_versao: Mapped[int] = mapped_column(Integer)
    ativa: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Credencial(Base):
    __tablename__ = "credenciais"
    __table_args__ = (UniqueConstraint("conexao_id", "tipo", "versao"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), index=True)
    conexao_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("conexoes.id", ondelete="CASCADE"))
    tipo: Mapped[str] = mapped_column(Text)
    versao: Mapped[int] = mapped_column(Integer, default=1)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    dek_versao: Mapped[int] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(64))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    expira_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    criado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    rotacionado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CredencialAcesso(Base):
    __tablename__ = "credencial_acessos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger)
    credencial_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("credenciais.id", ondelete="CASCADE"))
    job_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    finalidade: Mapped[str] = mapped_column(Text)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
