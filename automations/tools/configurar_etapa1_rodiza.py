"""Passo 4 da Etapa 1 — roda UMA vez, no Windows, com o IN-360 no ar:

  1. cria (se faltar) o cliente Rodiza e a loja Shopping BH;
  2. cadastra as conexões de integração que os scripts atuais já usam;
  3. leva cada senha do Gerenciador de Credenciais do Windows (keyring) para o
     cofre do IN-360 — sem exibir, gravar em arquivo ou logar o valor.

    py automations\\tools\\configurar_etapa1_rodiza.py
    py automations\\tools\\configurar_etapa1_rodiza.py --sem-senhas   # só cliente/loja/conexões

Pode rodar de novo sem duplicar nada. Senha já cadastrada no cofre não é
trocada (use --substituir para forçar nova versão). O keyring NÃO é apagado:
os scripts atuais continuam funcionando durante a transição.
"""
import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
API = os.environ.get("ERP_API", "http://127.0.0.1:8100")
EMAIL_RODIZA = "rodizaalimentos@gmail.com"

# integração, nome da conexão, parâmetros (NÃO secretos), tipo de segredo,
# alvo no keyring, usuário no keyring (None = pergunta na hora)
CONEXOES = [
    ("gcom", "GCOM — Rodiza", {"empresa": "rodiza", "usuario": "rodrigo", "rede": "GIRAFFAS",
                               "unidade": "SHOPPING BH"}, "password", "GCOM_Rodiza", "rodrigo"),
    ("email_imap", "E-mail rodizaalimentos (IMAP)", {"email": EMAIL_RODIZA, "servidor": "imap.gmail.com"},
     "imap_app_password", "GMAIL_Rodiza", EMAIL_RODIZA),
    ("ifood_portal", "iFood — Portal do Parceiro", {"usuario": EMAIL_RODIZA}, "password", "IFOOD_Rodiza",
     EMAIL_RODIZA),
    ("pluxee_portal", "Pluxee — Estabelecimentos", {"usuario": EMAIL_RODIZA, "otp": "email_imap"}, "password",
     "PLUXEE_Rodiza", EMAIL_RODIZA),
    ("vr_portal", "VR — Estabelecimento", {"usuario": EMAIL_RODIZA}, "password", "VR_Rodiza", EMAIL_RODIZA),
    ("alelo_portal", "Alelo — Meu Estabelecimento", {}, "password", "ALELO_Rodiza", None),
    ("ticket_portal", "Ticket — Estabelecimento", {}, "password", "TICKET_Rodiza", None),
]
PERGUNTA_USUARIO = {
    "ALELO_Rodiza": "CPF usado no login da Alelo (só números)",
    "TICKET_Rodiza": "Login do portal Ticket (CNPJ, só números)",
}


class Api:
    def __init__(self, base: str):
        self.base, self.token = base.rstrip("/"), None

    def req(self, metodo: str, caminho: str, corpo: dict | None = None, ok404: bool = False):
        dados = json.dumps(corpo).encode() if corpo is not None else None
        r = urllib.request.Request(self.base + caminho, data=dados, method=metodo,
                                   headers={"Content-Type": "application/json"})
        if self.token:
            r.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                return json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as e:
            if ok404 and e.code == 404:
                return None
            sys.exit(f"\nErro {e.code} em {metodo} {caminho}: {e.read().decode(errors='replace')}")
        except urllib.error.URLError as e:
            sys.exit(f"\nIN-360 fora do ar em {self.base}? ({e.reason})")

    def login(self, email: str, senha: str):
        self.token = self.req("POST", "/auth/login", {"email": email, "senha": senha})["access_token"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sem-senhas", action="store_true", help="não mexe no cofre")
    ap.add_argument("--substituir", action="store_true", help="grava nova versão mesmo se já houver senha")
    a = ap.parse_args()

    keyring = None
    if not a.sem_senhas:
        import keyring  # noqa: F811 — só exigido quando for levar senhas

    api = Api(API)
    email = os.environ.get("ERP_EMAIL") or input("Seu e-mail no IN-360: ").strip()
    senha = os.environ.get("ERP_SENHA") or getpass.getpass("Sua senha do IN-360 (não aparece): ")
    api.login(email, senha)
    del senha

    # 1. cliente e loja
    tenant = next((t for t in api.req("GET", "/tenants") if t["codigo"] == "rodiza"), None)
    if tenant is None:
        tenant = api.req("POST", "/tenants", {"rede_codigo": "giraffas", "rede_nome": "Giraffas",
                                              "codigo": "rodiza", "razao_social": "Rodiza Alimentos Ltda"})
        print(f"[criado ] cliente rodiza (id {tenant['id']})")
    else:
        print(f"[existe ] cliente rodiza (id {tenant['id']})")
    tid = tenant["id"]
    loja = next((l for l in api.req("GET", f"/tenants/{tid}/lojas") if l.get("filial_sigla") == "GSHBH"), None)
    if loja is None:
        loja = api.req("POST", f"/tenants/{tid}/lojas", {"nome": "Shopping BH", "filial_sigla": "GSHBH"})
        print(f"[criado ] loja Shopping BH (id {loja['id']})")
    else:
        print(f"[existe ] loja Shopping BH (id {loja['id']})")

    # 2. conexões + 3. senhas
    existentes = {c["nome"]: c for c in api.req("GET", f"/tenants/{tid}/conexoes")}
    resumo = []
    for integ, nome, params, tipo, alvo, usuario_kr in CONEXOES:
        params = dict(params)
        if usuario_kr is None and alvo in PERGUNTA_USUARIO:
            atual = existentes.get(nome, {}).get("parametros", {}).get("usuario")
            usuario_kr = atual or input(f"{PERGUNTA_USUARIO[alvo]}: ").strip()
            params["usuario"] = usuario_kr
        con = existentes.get(nome)
        if con is None:
            con = api.req("POST", f"/tenants/{tid}/conexoes",
                          {"integracao": integ, "nome": nome, "parametros": params})
            cadastradas, status_con = [], "criada"
        else:
            cadastradas, status_con = con.get("segredos_cadastrados", []), "existia"

        if a.sem_senhas:
            status_senha = "não mexido (--sem-senhas)"
        elif tipo in cadastradas and not a.substituir:
            status_senha = "já estava no cofre"
        else:
            valor = keyring.get_password(alvo, usuario_kr) if usuario_kr else None
            if not valor:
                status_senha = "NÃO achada no Windows — cadastrar depois"
            else:
                meta = api.req("PUT", f"/conexoes/{con['id']}/credenciais/{tipo}", {"valor": valor})
                status_senha = f"levada ao cofre (versão {meta['versao']}, impressão {meta['impressao']})"
            del valor
        resumo.append((nome, status_con, status_senha))

    print("\nConexão".ljust(36), "| Conexão | Senha")
    for nome, sc, ss in resumo:
        print(f"{nome:<35} | {sc:<7} | {ss}")
    print("\nPronto. O keyring do Windows não foi alterado.")


if __name__ == "__main__":
    main()
