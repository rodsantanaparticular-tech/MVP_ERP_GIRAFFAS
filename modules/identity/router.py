from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.audit import AuditLog, registrar
from core.config import settings
from core.db import get_db
from core.security.auth import criar_token, hash_senha, usuario_atual, verificar_senha
from core.security.rbac import Contexto, carregar_atribuicoes, carregar_papeis, exige_permissao
from modules.identity.models import PapelAcesso, Permissao, PapelPermissao, Usuario, UsuarioLoja, UsuarioPapel
from modules.tenants.models import Loja

router = APIRouter(tags=["identidade"])


# --- schemas ------------------------------------------------------------------
class LoginIn(BaseModel):
    email: str
    senha: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AlterarSenhaIn(BaseModel):
    senha_atual: str
    senha_nova: str


class UsuarioIn(BaseModel):
    email: EmailStr
    nome: str
    senha_inicial: str


class AtribuicaoIn(BaseModel):
    papel: str
    tenant_id: int | None = None
    loja_id: int | None = None


# --- login com bloqueio por tentativas ------------------------------------------
def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _autenticar(db: Session, email: str, senha: str, ip: str | None) -> str:
    email = email.strip().lower()
    desde = datetime.utcnow() - timedelta(minutes=settings.login_janela_minutos)
    falhas = db.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.acao == "login_falha", AuditLog.criado_em >= desde,
        AuditLog.detalhes["email"].as_string() == email))
    if falhas >= settings.login_max_falhas:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="Muitas tentativas. Tente de novo mais tarde.")
    usuario = db.scalar(select(Usuario).where(func.lower(Usuario.email) == email))
    if not usuario or not usuario.ativo or not verificar_senha(senha, usuario.senha_hash):
        registrar(db, "login_falha", "usuario", usuario.id if usuario else None, detalhes={"email": email}, ip=ip)
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="E-mail ou senha inválidos")
    registrar(db, "login_ok", "usuario", usuario.id, usuario_id=usuario.id, ip=ip)
    db.commit()
    return criar_token(usuario.id)


@router.post("/auth/login", response_model=Token)
def login(dados: LoginIn, request: Request, db: Session = Depends(get_db)):
    return Token(access_token=_autenticar(db, dados.email, dados.senha, _ip(request)))


@router.post("/auth/token", response_model=Token, include_in_schema=False)
def token_form(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Mesmo login, no formato do botão 'Authorize' do /docs."""
    return Token(access_token=_autenticar(db, form.username, form.password, _ip(request)))


@router.get("/auth/me")
def me(usuario: Usuario = Depends(usuario_atual), db: Session = Depends(get_db)):
    legado = [a.papel.value for a in db.scalars(select(UsuarioLoja).where(UsuarioLoja.usuario_id == usuario.id))]
    return {
        "id": usuario.id, "email": usuario.email, "nome": usuario.nome, "ativo": usuario.ativo,
        "papeis": legado,  # formato antigo, usado pelo front do Raio-X
        "atribuicoes": [{"papel": p, "tenant_id": t, "loja_id": l} for p, t, l in carregar_papeis(db, usuario.id)],
        "permissoes": sorted({a.permissao for a in carregar_atribuicoes(db, usuario.id)}),
    }


@router.post("/auth/alterar-senha")
def alterar_senha(dados: AlterarSenhaIn, request: Request, usuario: Usuario = Depends(usuario_atual),
                  db: Session = Depends(get_db)):
    if not verificar_senha(dados.senha_atual, usuario.senha_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Senha atual incorreta")
    _valida_senha(dados.senha_nova)
    usuario.senha_hash = hash_senha(dados.senha_nova)
    registrar(db, "senha_alterada", "usuario", usuario.id, usuario_id=usuario.id, ip=_ip(request))
    db.commit()
    return {"ok": True}


def _valida_senha(senha: str) -> None:
    if len(senha) < settings.senha_min_caracteres:
        raise HTTPException(status_code=422,
                            detail=f"A senha precisa ter pelo menos {settings.senha_min_caracteres} caracteres")


# --- perfis e usuários ----------------------------------------------------------
@router.get("/papeis")
def listar_papeis(usuario: Usuario = Depends(usuario_atual), db: Session = Depends(get_db)):
    papeis = db.scalars(select(PapelAcesso).order_by(PapelAcesso.id)).all()
    perms = db.execute(select(PapelPermissao.papel_id, Permissao.codigo)
                       .join(Permissao, Permissao.id == PapelPermissao.permissao_id)).all()
    por_papel: dict[int, list[str]] = {}
    for pid, cod in perms:
        por_papel.setdefault(pid, []).append(cod)
    return [{"codigo": p.codigo, "escopo": p.escopo, "descricao": p.descricao,
             "permissoes": sorted(por_papel.get(p.id, []))} for p in papeis]


@router.post("/usuarios", status_code=201)
def criar_usuario(dados: UsuarioIn, request: Request, ctx: Contexto = Depends(exige_permissao("usuarios:gerir"))):
    db = ctx.db
    _valida_senha(dados.senha_inicial)
    email = dados.email.strip().lower()
    if db.scalar(select(Usuario).where(func.lower(Usuario.email) == email)):
        raise HTTPException(status_code=409, detail="E-mail já cadastrado")
    u = Usuario(email=email, nome=dados.nome, senha_hash=hash_senha(dados.senha_inicial), ativo=True)
    db.add(u)
    db.flush()
    registrar(db, "usuario_criado", "usuario", u.id, usuario_id=ctx.usuario.id, ip=_ip(request))
    db.commit()
    return {"id": u.id, "email": u.email, "nome": u.nome}


@router.post("/usuarios/{usuario_id}/papeis", status_code=201)
def atribuir_papel(usuario_id: int, dados: AtribuicaoIn, request: Request,
                   ctx: Contexto = Depends(exige_permissao("usuarios:gerir"))):
    db = ctx.db
    papel = db.scalar(select(PapelAcesso).where(PapelAcesso.codigo == dados.papel))
    if papel is None:
        raise HTTPException(status_code=404, detail="Papel inexistente")
    if db.get(Usuario, usuario_id) is None:
        raise HTTPException(status_code=404, detail="Usuário inexistente")

    # coerência entre papel e escopo
    if papel.escopo == "plataforma" and (dados.tenant_id or dados.loja_id):
        raise HTTPException(status_code=422, detail="Papel de plataforma não tem cliente/loja")
    if papel.escopo in ("tenant", "loja") and dados.tenant_id is None:
        raise HTTPException(status_code=422, detail="Informe o cliente (tenant_id)")
    if papel.escopo == "loja" and dados.loja_id is None:
        raise HTTPException(status_code=422, detail="Informe a loja (loja_id)")
    if dados.loja_id is not None:
        loja = db.get(Loja, dados.loja_id)
        if loja is None or loja.tenant_id != dados.tenant_id:
            raise HTTPException(status_code=422, detail="Loja não pertence a esse cliente")

    # anti-escalada: só a plataforma cria papel de plataforma; e ninguém concede
    # permissão que não tem naquele escopo
    if papel.escopo == "plataforma":
        ctx.exigir("plataforma:admin")
    else:
        ctx.exigir("usuarios:gerir", dados.tenant_id, dados.loja_id)
        perms_do_papel = db.scalars(select(Permissao.codigo).join(PapelPermissao)
                                    .where(PapelPermissao.papel_id == papel.id)).all()
        faltando = [p for p in perms_do_papel if not ctx.pode(p, dados.tenant_id, dados.loja_id)]
        if faltando:
            raise HTTPException(status_code=403,
                                detail=f"Você não pode conceder permissões que não tem: {', '.join(faltando)}")

    existente = db.scalar(select(UsuarioPapel).where(
        UsuarioPapel.usuario_id == usuario_id, UsuarioPapel.papel_id == papel.id,
        UsuarioPapel.tenant_id.is_(None) if dados.tenant_id is None else UsuarioPapel.tenant_id == dados.tenant_id,
        UsuarioPapel.loja_id.is_(None) if dados.loja_id is None else UsuarioPapel.loja_id == dados.loja_id))
    if existente:
        return {"id": existente.id, "ja_existia": True}
    up = UsuarioPapel(usuario_id=usuario_id, papel_id=papel.id, tenant_id=dados.tenant_id, loja_id=dados.loja_id,
                      criado_por=ctx.usuario.id)
    db.add(up)
    db.flush()
    registrar(db, "papel_atribuido", "usuario", usuario_id, usuario_id=ctx.usuario.id, tenant_id=dados.tenant_id,
              detalhes={"papel": dados.papel, "loja_id": dados.loja_id}, ip=_ip(request))
    db.commit()
    return {"id": up.id, "ja_existia": False}


@router.delete("/usuarios/{usuario_id}/papeis/{atribuicao_id}")
def remover_papel(usuario_id: int, atribuicao_id: int, request: Request,
                  ctx: Contexto = Depends(exige_permissao("usuarios:gerir"))):
    db = ctx.db
    up = db.get(UsuarioPapel, atribuicao_id)
    if up is None or up.usuario_id != usuario_id:
        raise HTTPException(status_code=404, detail="Atribuição inexistente")
    if up.tenant_id is None:
        ctx.exigir("plataforma:admin")
    else:
        ctx.exigir("usuarios:gerir", up.tenant_id, up.loja_id)
    registrar(db, "papel_removido", "usuario", usuario_id, usuario_id=ctx.usuario.id, tenant_id=up.tenant_id,
              detalhes={"papel_id": up.papel_id, "loja_id": up.loja_id}, ip=_ip(request))
    db.delete(up)
    db.commit()
    return {"ok": True}
