from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from core.config import jwt_secret, settings
from core.db import get_db
from modules.identity.models import Usuario

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def hash_senha(senha: str) -> str:
    return bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verificar_senha(senha: str, senha_hash: str) -> bool:
    return bcrypt.checkpw(senha.encode("utf-8"), senha_hash.encode("utf-8"))


def criar_token(usuario_id: int) -> str:
    expira = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    return jwt.encode({"sub": str(usuario_id), "exp": expira}, jwt_secret(), algorithm="HS256")


def usuario_atual(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> Usuario:
    erro = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas",
                         headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, jwt_secret(), algorithms=["HS256"])
        usuario_id = int(payload.get("sub"))
    except (JWTError, TypeError, ValueError):
        raise erro
    usuario = db.get(Usuario, usuario_id)
    if usuario is None or not usuario.ativo:
        raise erro
    return usuario
