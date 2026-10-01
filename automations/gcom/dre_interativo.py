"""DRE Interativo do GCOM — SOMENTE LEITURA (roda no Windows, navegador visível: o WAF bloqueia headless).

    py automations\\gcom\\dre_interativo.py --mes Agosto:2026-08 --explorar
        abre o DRE do mês, tira prints e lista passos/botões (nada é baixado)
    py automations\\gcom\\dre_interativo.py --mes Agosto:2026-08 --passo "<nome do passo>"
        abre o passo e baixa a exportação Excel para C:\\giraffas-erp-data\\entrada\\

Login e navegação copiados de in-360-giraffas/scripts/gcom_extract_despesas.py (o original não é
alterado). A senha vem do Gerenciador de Credenciais do Windows (GCOM_Rodiza) e nunca é exibida.
Este script NÃO clica em salvar, editar, excluir, efetivar ou qualquer ação de escrita.
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import keyring
from playwright.sync_api import sync_playwright

GCOM_LOGIN = "https://www2.gcom.com.br/Cloud/Home/Login.aspx"
GCOM_COMPANY, GCOM_USER, CRED_TARGET = "rodiza", "rodrigo", "GCOM_Rodiza"
ENTRADA = Path(r"C:\giraffas-erp-data\entrada")
CHROMIUM_ARGS = ["--disable-dev-shm-usage", "--disable-gpu", "--disable-extensions",
                 "--disable-background-networking", "--no-sandbox", "--js-flags=--max-old-space-size=512"]
# Palavras que NUNCA podem ser clicadas por este script (escrita no GCOM).
PROIBIDO = re.compile(r"salvar|gravar|excluir|cancelar doc|efetivar|autorizar|baixa|estornar|confirmar pag",
                      re.IGNORECASE)


def abrir_dre(ctx, page, mes_label: str, mes_iso: str):
    page.goto(GCOM_LOGIN, timeout=60000)
    page.locator("#ctl00_ContentBody_txtCompanyName").fill(GCOM_COMPANY)
    page.locator("#ctl00_ContentBody_txtUserName").fill(GCOM_USER)
    senha = keyring.get_password(CRED_TARGET, GCOM_USER)
    if not senha:
        sys.exit("Credencial GCOM_Rodiza não encontrada no Gerenciador de Credenciais do Windows.")
    page.locator("#ctl00_ContentBody_txtPassword").fill(senha)
    del senha
    page.get_by_role("button", name="Login").click()
    page.wait_for_load_state("networkidle")
    try:
        page.locator("[id^='divMsgNotificacao']").get_by_text("close").click(timeout=5000)
    except Exception:
        pass
    cy = 412
    page.mouse.move(40, cy); page.wait_for_timeout(300)
    page.mouse.move(130, cy); page.wait_for_timeout(300)
    page.mouse.click(130, cy); page.wait_for_timeout(1200)
    page.get_by_text("Finanças", exact=True).click(); page.wait_for_timeout(800)
    page.mouse.click(94, 864); page.wait_for_timeout(1200)
    with ctx.expect_page() as popup:
        page.get_by_text("DRE INTERATIVO", exact=True).click()
    dre = popup.value
    dre.wait_for_load_state(); dre.wait_for_timeout(1500)
    dre.locator("select").first.select_option(label="GIRAFFAS"); dre.wait_for_timeout(1200)
    dre.get_by_text("SHOPPING BH", exact=False).first.click(); dre.wait_for_timeout(1200)
    ano = mes_iso.split("-")[0]
    dre.get_by_text(f"{ano} - 0/12", exact=True).first.click(); dre.wait_for_timeout(400)
    dre.get_by_role("button", name=mes_label).first.click(); dre.wait_for_timeout(400)
    dre.get_by_role("button", name="Confirmar").first.click()   # confirma o FILTRO de período (leitura)
    dre.wait_for_timeout(11000)
    return dre


def clicaveis(dre) -> list[str]:
    return dre.evaluate("""() => Array.from(document.querySelectorAll('a,button,li,[role=tab],[onclick]'))
        .filter(e => e.offsetParent !== null).map(e => (e.innerText||e.title||'').trim().replace(/\\s+/g,' '))
        .filter(t => t && t.length < 60)""")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--mes", required=True, help="ex.: Agosto:2026-08")
    ap.add_argument("--explorar", action="store_true")
    ap.add_argument("--passo", help="texto exato do passo/aba do DRE a exportar")
    ap.add_argument("--saida", type=Path, help="pasta para prints/diagnóstico (modo --explorar)")
    a = ap.parse_args()
    mes_label, mes_iso = a.mes.split(":")
    saida = a.saida or ENTRADA / "_diagnostico_dre"
    saida.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=CHROMIUM_ARGS)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
        page = ctx.new_page()
        page.on("dialog", lambda d: d.dismiss())
        try:
            dre = abrir_dre(ctx, page, mes_label, mes_iso)
            if a.explorar:
                dre.screenshot(path=str(saida / f"dre_{mes_iso}_inicio.png"), full_page=True)
                (saida / f"dre_{mes_iso}_texto.txt").write_text(dre.evaluate("document.body.innerText"),
                                                                 encoding="utf-8")
                itens = clicaveis(dre)
                (saida / f"dre_{mes_iso}_clicaveis.json").write_text(json.dumps(itens, ensure_ascii=False, indent=1),
                                                                     encoding="utf-8")
                print(f"Explorado. Prints e textos em {saida}")
                return 0
            if not a.passo:
                sys.exit("Informe --explorar ou --passo.")
            if PROIBIDO.search(a.passo):
                sys.exit(f"Recusado: '{a.passo}' parece ação de escrita.")
            dre.get_by_text(a.passo, exact=True).first.click()
            dre.wait_for_timeout(5000)
            dre.screenshot(path=str(saida / f"dre_{mes_iso}_{a.passo}.png"), full_page=True)
            (saida / f"dre_{mes_iso}_{a.passo}.txt").write_text(dre.evaluate("document.body.innerText"),
                                                                encoding="utf-8")
            botao = dre.locator("button:has-text('Excel'), a:has-text('Excel'), [title*='Excel' i]").first
            with dre.expect_download(timeout=60000) as dl:
                botao.click()
            nome = f"DRE_GCOM_{mes_iso}_{re.sub(r'[^A-Za-z0-9]+', '_', a.passo)}{Path(dl.value.suggested_filename).suffix}"
            destino = ENTRADA / nome
            dl.value.save_as(str(destino))
            print(f"Baixado: {destino}  ({datetime.now():%d-%m-%Y %H:%M})")
            return 0
        except Exception as e:
            try:
                page.context.pages[-1].screenshot(path=str(saida / f"erro_{mes_iso}.png"))
            except Exception:
                pass
            print(f"ERRO: {e}")
            return 1
        finally:
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
