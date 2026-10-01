import enum
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import Base


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    nome: Mapped[str] = mapped_column(String(120))
    senha_hash: Mapped[str] = mapped_column(String(200))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    acessos: Mapped[list["UsuarioLoja"]] = relationship(back_populates="usuario")


# --- Legado do Raio-X (mantido até o front do Raio-X migrar para RBAC) --------

class Papel(str, enum.Enum):
    gestor = "gestor"
    auditor = "auditor"
    colaborador = "colaborador"


class UsuarioLoja(Base):
    __tablename__ = "usuario_loja"
    __table_args__ = (UniqueConstraint("usuario_id", "loja_id", name="uq_usuario_loja"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    loja_id: Mapped[int] = mapped_column(ForeignKey("lojas.id"))
    papel: Mapped[Papel] = mapped_column(Enum(Papel, name="papel_enum"))

    usuario: Mapped["Usuario"] = relationship(back_populates="acessos")


# --- RBAC -----------------------------------------------------------------------

class PapelAcesso(Base):
    __tablename__ = "papeis"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    codigo: Mapped[str] = mapped_column(Text, unique=True)
    escopo: Mapped[str] = mapped_column(Text)  # plataforma | tenant | loja
    descricao: Mapped[str | None] = mapped_column(Text, nullable=True)


class Permissao(Base):
    __tablename__ = "permissoes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    codigo: Mapped[str] = mapped_column(Text, unique=True)
    descricao: Mapped[str | None] = mapped_column(Text, nullable=True)


class PapelPermissao(Base):
    __tablename__ = "papel_permissao"

    papel_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("papeis.id", ondelete="CASCADE"), primary_key=True)
    permissao_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("permissoes.id", ondelete="CASCADE"),
                                              primary_key=True)


class UsuarioPapel(Base):
    __tablename__ = "usuario_papel"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"))
    papel_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("papeis.id"))
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=True)
    loja_id: Mapped[int | None] = mapped_column(ForeignKey("lojas.id"), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    criado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
