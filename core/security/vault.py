"""Cofre de senhas: cifragem envelope.

  chave-mestra (KEK, arquivo fora do banco)
     └─ cifra a DEK de cada tenant (tabela tenant_chaves)
           └─ cifra cada segredo (tabela credenciais), com AAD = tenant|conexão|tipo|versão
              → um segredo copiado para outra linha/cliente não decifra.

Nenhuma rota da API devolve segredo, exceto `revelar` (permissão própria,
motivo obrigatório, registrado). Toda leitura grava credencial_acessos.
"""
import hashlib
import hmac
import os
from datetime import datetime

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from core.config import master_key, settings
from core.db import usar_tenant
from modules.integrations.models import Credencial, CredencialAcesso, TenantChave


def _aad(*partes) -> bytes:
    return "|".join(str(p) for p in partes).encode()


class Cofre:
    def __init__(self, db: Session):
        self.db = db
        self._kek = AESGCM(master_key())
        self._kek_versao = settings.erp_master_key_version

    # --- chaves por tenant ----------------------------------------------------
    def _dek(self, tenant_id: int, versao: int | None = None, criar: bool = True) -> tuple[bytes, int]:
        usar_tenant(self.db, tenant_id)
        q = select(TenantChave).where(TenantChave.tenant_id == tenant_id)
        q = q.where(TenantChave.versao == versao) if versao is not None else q.where(TenantChave.ativa.is_(True))
        chave = self.db.scalar(q)
        if chave is None:
            if versao is not None or not criar:
                raise LookupError(f"chave do tenant {tenant_id} (versão {versao}) não encontrada")
            dek, nonce = AESGCM.generate_key(bit_length=256), os.urandom(12)
            chave = TenantChave(tenant_id=tenant_id, versao=1, nonce=nonce, kek_versao=self._kek_versao,
                                dek_cifrada=self._kek.encrypt(nonce, dek, _aad("tenant", tenant_id, "dek", 1)))
            self.db.add(chave)
            self.db.flush()
            return dek, 1
        dek = self._kek.decrypt(chave.nonce, chave.dek_cifrada, _aad("tenant", tenant_id, "dek", chave.versao))
        return dek, chave.versao

    def _fingerprint(self, tenant_id: int, valor: str) -> str:
        chave = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                     info=_aad("fingerprint", tenant_id)).derive(master_key())
        return hmac.new(chave, valor.encode("utf-8"), hashlib.sha256).hexdigest()

    # --- API do cofre -----------------------------------------------------------
    def gravar(self, tenant_id: int, conexao_id: int, tipo: str, valor: str, *,
               usuario_id: int | None = None, expira_em: datetime | None = None) -> Credencial:
        """Cria nova versão do segredo e desativa a anterior (rotação)."""
        if not valor:
            raise ValueError("valor vazio")
        dek, dek_versao = self._dek(tenant_id)
        atual = self.db.scalar(select(Credencial).where(
            Credencial.conexao_id == conexao_id, Credencial.tipo == tipo, Credencial.ativo.is_(True)))
        versao = 1
        if atual is not None:
            versao = atual.versao + 1
            self.db.execute(update(Credencial).where(Credencial.id == atual.id)
                            .values(ativo=False, rotacionado_em=datetime.utcnow()))
        nonce = os.urandom(12)
        cred = Credencial(
            tenant_id=tenant_id, conexao_id=conexao_id, tipo=tipo, versao=versao,
            ciphertext=AESGCM(dek).encrypt(nonce, valor.encode("utf-8"), _aad(tenant_id, conexao_id, tipo, versao)),
            nonce=nonce, dek_versao=dek_versao, fingerprint=self._fingerprint(tenant_id, valor),
            ativo=True, expira_em=expira_em, criado_por=usuario_id)
        self.db.add(cred)
        self.db.flush()
        return cred

    def ler(self, cred: Credencial, *, finalidade: str, usuario_id: int | None = None,
            job_id: int | None = None) -> str:
        dek, _ = self._dek(cred.tenant_id, versao=cred.dek_versao)
        valor = AESGCM(dek).decrypt(cred.nonce, cred.ciphertext,
                                    _aad(cred.tenant_id, cred.conexao_id, cred.tipo, cred.versao)).decode("utf-8")
        self.db.add(CredencialAcesso(tenant_id=cred.tenant_id, credencial_id=cred.id, usuario_id=usuario_id,
                                     job_id=job_id, finalidade=finalidade))
        self.db.flush()
        return valor

    def ler_ativa(self, tenant_id: int, conexao_id: int, tipo: str, **kw) -> str:
        usar_tenant(self.db, tenant_id)
        cred = self.db.scalar(select(Credencial).where(
            Credencial.conexao_id == conexao_id, Credencial.tipo == tipo, Credencial.ativo.is_(True)))
        if cred is None:
            raise LookupError(f"credencial '{tipo}' não cadastrada na conexão {conexao_id}")
        return self.ler(cred, **kw)
