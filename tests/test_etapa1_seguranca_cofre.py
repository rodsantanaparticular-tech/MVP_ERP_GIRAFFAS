"""Etapa 1 — perfis de acesso e cofre de senhas.

Roda contra o Postgres real (papel da aplicação, com RLS), dentro do contêiner:
    docker compose run --rm api pytest -q
"""
import uuid

import pytest
from cryptography.exceptions import InvalidTag
from fastapi.testclient import TestClient
from sqlalchemy import select, text

import modules.models  # noqa: F401
from api.main import app
from core.db import nova_sessao, usar_tenant
from core.security.auth import hash_senha
from core.security.vault import Cofre
from modules.identity.models import PapelAcesso, Usuario, UsuarioPapel
from modules.integrations.models import Credencial, CredencialAcesso

SENHA = "senha-de-teste-123"
GCOM_SENHA = "S3gredo-GCOM-nao-pode-vazar"
client = TestClient(app)


def _sufixo() -> str:
    return uuid.uuid4().hex[:8]


def criar_usuario(papel: str | None = None, tenant_id: int | None = None, loja_id: int | None = None) -> str:
    email = f"u{_sufixo()}@exemplo.com.br"
    with nova_sessao() as db:
        u = Usuario(email=email, nome="Teste", senha_hash=hash_senha(SENHA), ativo=True)
        db.add(u)
        db.flush()
        if papel:
            pid = db.scalar(select(PapelAcesso.id).where(PapelAcesso.codigo == papel))
            db.add(UsuarioPapel(usuario_id=u.id, papel_id=pid, tenant_id=tenant_id, loja_id=loja_id))
        db.commit()
    return email


def login(email: str, senha: str = SENHA) -> dict:
    r = client.post("/auth/login", json={"email": email, "senha": senha})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def cenario():
    """Admin da plataforma cria 2 clientes (A e B), 1 loja em cada e uma conexão GCOM em cada."""
    adm = login(criar_usuario("plataforma_admin"))
    ids = {}
    for nome in ("A", "B"):
        r = client.post("/tenants", headers=adm, json={"rede_codigo": "giraffas", "codigo": f"t{nome}{_sufixo()}",
                                                         "razao_social": f"Cliente {nome}"})
        assert r.status_code == 201, r.text
        tid = r.json()["id"]
        r = client.post(f"/tenants/{tid}/lojas", headers=adm, json={"nome": f"Loja {nome}", "filial_sigla": "L1"})
        assert r.status_code == 201, r.text
        loja = r.json()["id"]
        r = client.post(f"/tenants/{tid}/conexoes", headers=adm, json={
            "integracao": "gcom", "nome": "GCOM", "loja_id": loja,
            "parametros": {"empresa": "empresa-x", "usuario": "usuario-x", "unidade": f"LOJA {nome}"}})
        assert r.status_code == 201, r.text
        ids[nome] = {"tenant": tid, "loja": loja, "conexao": r.json()["id"]}
    return {"adm": adm, **ids}


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_login_errado_e_bloqueio():
    email = criar_usuario()
    for _ in range(3):
        assert client.post("/auth/login", json={"email": email, "senha": "errada"}).status_code == 401
    # LOGIN_MAX_FALHAS=3 no ambiente de teste: agora até a senha certa é barrada
    assert client.post("/auth/login", json={"email": email, "senha": SENHA}).status_code == 429


def test_sem_token_nao_entra():
    assert client.get("/integracoes").status_code == 401


def test_cofre_grava_sem_devolver_e_cifra_no_banco(cenario):
    adm, a = cenario["adm"], cenario["A"]
    r = client.put(f"/conexoes/{a['conexao']}/credenciais/password", headers=adm, json={"valor": GCOM_SENHA})
    assert r.status_code == 200, r.text
    assert GCOM_SENHA not in r.text and "valor" not in r.json()

    r = client.get(f"/conexoes/{a['conexao']}/credenciais", headers=adm)
    assert r.status_code == 200 and GCOM_SENHA not in r.text

    with nova_sessao() as db:
        usar_tenant(db, a["tenant"])
        cred = db.scalar(select(Credencial).where(Credencial.conexao_id == a["conexao"], Credencial.ativo.is_(True)))
        assert GCOM_SENHA.encode() not in cred.ciphertext
        assert Cofre(db).ler(cred, finalidade="teste") == GCOM_SENHA
        db.commit()


def test_rotacao_mantem_historico(cenario):
    adm, b = cenario["adm"], cenario["B"]
    for v in ("primeira-senha", "segunda-senha"):
        assert client.put(f"/conexoes/{b['conexao']}/credenciais/password", headers=adm,
                          json={"valor": v}).status_code == 200
    hist = client.get(f"/conexoes/{b['conexao']}/credenciais?historico=true", headers=adm).json()
    assert [h["versao"] for h in hist] == [2, 1]
    assert [h["ativo"] for h in hist] == [True, False]


def test_revelar_exige_motivo_e_fica_registrado(cenario):
    adm, a = cenario["adm"], cenario["A"]
    client.put(f"/conexoes/{a['conexao']}/credenciais/password", headers=adm, json={"valor": GCOM_SENHA})
    assert client.post(f"/conexoes/{a['conexao']}/credenciais/password/revelar", headers=adm,
                       json={"motivo": "curto"}).status_code == 422
    r = client.post(f"/conexoes/{a['conexao']}/credenciais/password/revelar", headers=adm,
                    json={"motivo": "conferir login no portal com o gerente"})
    assert r.status_code == 200 and r.json()["valor"] == GCOM_SENHA
    with nova_sessao() as db:
        usar_tenant(db, a["tenant"])
        acessos = db.scalars(select(CredencialAcesso.finalidade).join(Credencial)
                             .where(Credencial.conexao_id == a["conexao"])).all()
        assert any("conferir login no portal" in f for f in acessos)


def test_parametro_com_cara_de_senha_e_recusado(cenario):
    r = client.post(f"/tenants/{cenario['A']['tenant']}/conexoes", headers=cenario["adm"], json={
        "integracao": "gcom", "nome": "errado", "parametros": {"empresa": "x", "usuario": "y", "senha": "123"}})
    assert r.status_code == 422 and "cofre" in r.text


def test_tipo_de_segredo_invalido(cenario):
    r = client.put(f"/conexoes/{cenario['A']['conexao']}/credenciais/api_key", headers=cenario["adm"],
                   json={"valor": "x"})
    assert r.status_code == 422


def test_eng_dados_so_no_proprio_cliente_e_nao_revela(cenario):
    a, b = cenario["A"], cenario["B"]
    eng = login(criar_usuario("eng_dados", tenant_id=a["tenant"]))
    assert client.put(f"/conexoes/{a['conexao']}/credenciais/password", headers=eng,
                      json={"valor": "nova"}).status_code == 200
    # cliente alheio: nem sabe que existe
    assert client.put(f"/conexoes/{b['conexao']}/credenciais/password", headers=eng,
                      json={"valor": "x"}).status_code == 404
    assert client.get(f"/tenants/{b['tenant']}/conexoes", headers=eng).status_code == 403
    # gravar sim, ver a senha não
    assert client.post(f"/conexoes/{a['conexao']}/credenciais/password/revelar", headers=eng,
                       json={"motivo": "tentando ver a senha"}).status_code == 403


def test_ti_ops_ve_metadados_mas_nao_grava(cenario):
    a = cenario["A"]
    ti = login(criar_usuario("ti_ops", tenant_id=a["tenant"]))
    assert client.get(f"/conexoes/{a['conexao']}/credenciais", headers=ti).status_code == 200
    assert client.put(f"/conexoes/{a['conexao']}/credenciais/password", headers=ti,
                      json={"valor": "x"}).status_code == 403


def test_gestor_de_loja_nao_ve_integracoes(cenario):
    a = cenario["A"]
    g = login(criar_usuario("gestor_loja", tenant_id=a["tenant"], loja_id=a["loja"]))
    assert client.get(f"/tenants/{a['tenant']}/conexoes", headers=g).status_code == 403
    assert client.get(f"/conexoes/{a['conexao']}/credenciais", headers=g).status_code == 403
    me = client.get("/auth/me", headers=g).json()
    assert "credenciais:gravar" not in me["permissoes"] and "dashboards:ler" in me["permissoes"]


def test_anti_escalada_de_privilegio(cenario):
    a = cenario["A"]
    fr = login(criar_usuario("franqueado_admin", tenant_id=a["tenant"]))
    alvo = client.post("/usuarios", headers=fr, json={"email": f"n{_sufixo()}@exemplo.com.br", "nome": "Nova",
                                                      "senha_inicial": SENHA}).json()["id"]
    # não pode criar admin de plataforma
    assert client.post(f"/usuarios/{alvo}/papeis", headers=fr,
                       json={"papel": "plataforma_admin"}).status_code == 403
    # não pode conceder o que não tem (eng_dados grava senhas; franqueado não)
    assert client.post(f"/usuarios/{alvo}/papeis", headers=fr,
                       json={"papel": "eng_dados", "tenant_id": a["tenant"]}).status_code == 403
    # pode conceder gestor da própria loja
    assert client.post(f"/usuarios/{alvo}/papeis", headers=fr,
                       json={"papel": "gestor_loja", "tenant_id": a["tenant"], "loja_id": a["loja"]}
                       ).status_code == 201


def test_rls_banco_isola_clientes(cenario):
    a, b = cenario["A"], cenario["B"]
    client.put(f"/conexoes/{a['conexao']}/credenciais/password", headers=cenario["adm"], json={"valor": GCOM_SENHA})
    with nova_sessao() as db:
        # sem cliente definido: o banco não devolve nada
        assert db.execute(text("SELECT count(*) FROM credenciais")).scalar() == 0
        db.rollback()
        # como cliente B: não enxerga as senhas do cliente A
        usar_tenant(db, b["tenant"])
        n = db.execute(text("SELECT count(*) FROM credenciais WHERE conexao_id = :c"), {"c": a["conexao"]}).scalar()
        assert n == 0


def test_segredo_copiado_para_outra_linha_nao_decifra(cenario):
    a = cenario["A"]
    client.put(f"/conexoes/{a['conexao']}/credenciais/password", headers=cenario["adm"], json={"valor": GCOM_SENHA})
    with nova_sessao() as db:
        usar_tenant(db, a["tenant"])
        cred = db.scalar(select(Credencial).where(Credencial.conexao_id == a["conexao"], Credencial.ativo.is_(True)))
        db.expunge(cred)
        cred.conexao_id = cred.conexao_id + 999  # mesmo ciphertext "grudado" em outra conexão
        with pytest.raises(InvalidTag):
            Cofre(db).ler(cred, finalidade="teste-adulteracao")
        db.rollback()
