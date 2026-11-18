"""Controle do navegador do robô (Playwright + Chromium embutido, perfil próprio — Q35).

Regras de segurança desta fase (F2):
- nunca digita senha: o login é feito pelo consultor na janela do robô (§3.3);
- nada é gravado no SGCOR: a 1ª tela é preenchida e o robô PARA (o registro só nasce no Avançar);
- "Pular" sai da tela sem salvar.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from pathlib import Path

from playwright.sync_api import Dialog, Page, sync_playwright

from ..config import Config
from ..modelos import Caso
from .paginas import Campo, LinhaApolice, campos_primeira_tela, escolher_apolice, ler_lista, normalizar_valor, \
    url_busca, url_lista, url_renovar

log = logging.getLogger("sgcor_renov.robo")


class SessaoExpirada(Exception):
    """O SGCOR pediu login de novo."""


class FalhaRobo(Exception):
    """Algo na tela não ficou como o esperado; vira pendência com o print da etapa."""


def _slug(texto: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", texto).strip("_")[:50]


class Robo:
    def __init__(self, cfg: Config, perfil: Path, prints: Path):
        self.cfg = cfg
        self.perfil = perfil
        self.prints = prints
        self._pw = None
        self._ctx = None
        self.page: Page | None = None

    # ------------------------------------------------------------ ciclo de vida

    def abrir(self) -> None:
        if self.page and not self.page.is_closed():
            return
        if self._pw is None:
            self._pw = sync_playwright().start()
        self.perfil.mkdir(parents=True, exist_ok=True)
        self._ctx = self._pw.chromium.launch_persistent_context(
            str(self.perfil), headless=False, no_viewport=True, args=["--start-maximized"],
            accept_downloads=False,
        )
        self.page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self.page.set_default_timeout(30000)
        self.page.on("dialog", self._dialogo)

    def fechar(self) -> None:
        try:
            if self._ctx:
                self._ctx.close()
        finally:
            if self._pw:
                self._pw.stop()
            self._pw = self._ctx = self.page = None

    @staticmethod
    def _dialogo(d: Dialog) -> None:
        # "Deseja sair? alterações não salvas" ao sair da tela sem salvar (Pular) → aceita; qualquer outro → recusa
        if d.type == "beforeunload":
            d.accept()
        else:
            log.warning("Diálogo inesperado do navegador recusado: %s %s", d.type, d.message)
            d.dismiss()

    # ------------------------------------------------------------ sessão

    def ir(self, url: str) -> None:
        self.abrir()
        self.page.goto(url, wait_until="load")
        if not self.logado():
            raise SessaoExpirada()
        self.esperar_tela()

    def esperar_tela(self, timeout_ms: int = 30000) -> None:
        """O SGCOR mostra '#conteudo-carregando' e esconde o formulário enquanto carrega dados por AJAX.
        Digitar antes disso faz o valor ser sobrescrito; então espera a tela assentar."""
        pg = self.page
        try:
            pg.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            pass
        if pg.locator("#conteudo-carregando").count():
            pg.wait_for_selector("#conteudo-carregando", state="hidden", timeout=timeout_ms)

    def logado(self) -> bool:
        """Logado = a página tem o menu com 'Sair' (onclick logout)."""
        return self.page.locator("[onclick*='logout']").count() > 0

    def verificar(self) -> bool:
        self.abrir()
        self.page.goto(url_lista(self.cfg), wait_until="domcontentloaded")
        return self.logado()

    def produtores(self) -> list[tuple[str, str]]:
        """Lista de produtores do SGCOR (Q36), lida do filtro 'Produtor Repasse' da pesquisa."""
        self.ir(url_lista(self.cfg))
        ops = self.page.eval_on_selector_all(
            "select#produtorRep option", "os => os.map(o => [o.value, o.textContent.trim()])")
        return [(v, t) for v, t in ops if v]

    # ------------------------------------------------------------ prints

    def print_(self, caso: Caso, etapa: str) -> Path | None:
        try:
            pasta = self.prints / date.today().strftime("%Y%m%d")
            pasta.mkdir(parents=True, exist_ok=True)
            arq = pasta / f"{datetime.now():%H%M%S}_{_slug(caso.nome)}_{_slug(etapa)}.png"
            self.page.screenshot(path=str(arq), full_page=True)
            return arq
        except Exception as e:  # print não pode derrubar o lote
            log.warning("Não consegui salvar o print (%s): %s", etapa, e)
            return None

    # ------------------------------------------------------------ busca

    def buscar(self, caso: Caso) -> LinhaApolice:
        """Q11/Q24/Q30. Tenta o CNPJ formatado e, sem resultado, só os dígitos."""
        linhas: list[LinhaApolice] = []
        for formatado in (True, False):
            self.ir(url_busca(self.cfg, caso.proposta.cnpj, caso.seguradora, formatado))
            linhas = ler_lista(self.page.content())
            if linhas:
                break
        self.print_(caso, "busca")
        linha, motivo = escolher_apolice(linhas, caso, self.cfg)
        if motivo:
            raise FalhaRobo(motivo)
        log.info("%s: apólice anterior no SGCOR = ID %s (apólice %s, %s a %s)", caso.nome, linha.proposta_id,
                 linha.apolice, linha.inicio, linha.fim)
        return linha

    # ------------------------------------------------------------ 1ª tela

    def preencher_renovacao(self, caso: Caso, linha: LinhaApolice) -> list[Campo]:
        """Abre 'Renovar' da apólice anterior e preenche só os campos da Q52. NÃO clica Avançar."""
        self.ir(url_renovar(self.cfg, linha.proposta_id))
        pg = self.page
        pg.wait_for_selector("#form-formulario")
        if pg.locator("select[name='tipo']").input_value() != "4":
            raise FalhaRobo("A tela aberta não é uma renovação (Tipo ≠ Renovação)")
        campos = campos_primeira_tela(caso, self.cfg)
        for c in campos:
            alvo = pg.locator(c.seletor).first
            if c.tipo == "checkbox":
                alvo.check()
            elif c.tipo == "select":
                alvo.select_option(c.valor)
            else:
                alvo.click()
                alvo.press("Control+A")
                alvo.press("Delete")
                alvo.press_sequentially(c.valor, delay=15)   # digita: as máscaras do SGCOR reagem a teclas
                alvo.press("Tab")
        # confere o que ficou na tela
        errados = []
        for c, atual in zip(campos, self.ler_campos(campos)):
            if normalizar_valor(atual) != normalizar_valor(c.valor):
                errados.append(f"{c.rotulo}: esperado “{c.valor}”, ficou “{atual}”")
        self.print_(caso, "primeira_tela_preenchida")
        if errados:
            raise FalhaRobo("Campos não aceitaram o valor: " + "; ".join(errados))
        return campos

    def ler_campos(self, campos: list[Campo]) -> list[str]:
        out = []
        for c in campos:
            alvo = self.page.locator(c.seletor).first
            if c.tipo == "checkbox":
                out.append("sim" if alvo.is_checked() else "não")
            else:
                out.append(alvo.input_value())
        return out

    def descartar(self) -> None:
        """Sai da tela sem salvar (Pular). Nada foi gravado: a renovação só nasce no Avançar."""
        if self.page and not self.page.is_closed():
            self.page.goto(url_lista(self.cfg), wait_until="domcontentloaded")
