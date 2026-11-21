"""Controle do navegador do robô (Playwright + Chromium embutido, perfil próprio — Q35).

Regras de segurança desta fase (F2):
- nunca digita senha: o login é feito pelo consultor na janela do robô (§3.3);
- nada é gravado no SGCOR: a 1ª tela é preenchida e o robô PARA (o registro só nasce no Avançar);
- "Pular" sai da tela sem salvar.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime
from pathlib import Path

from playwright.sync_api import Dialog, Page, sync_playwright

from ..config import INCLUIR_PADRAO, Config
from ..modelos import Caso
from ..numeros import formatar_dinheiro
from .paginas import Campo, LinhaApolice, anexos_existentes, campos_primeira_tela, conferir_parcelas, \
    escolher_apolice, itens_da_proposta, ler_coberturas_item, ler_lista, ler_parcelas, linhas_para_incluir, \
    marca_seguradora, mudou_de_ramo, normalizar_valor, plano_coberturas, plano_inclusoes, ramo_da_tela, url_busca, url_busca_cnpj, \
    url_editar_repasse, url_lista, url_renovar, vale_procurar_em_outros_ramos

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
        if self.page is not None:          # o consultor fechou a janela do robô: começa do zero
            self.fechar()
        try:
            if self._pw is None:
                self._pw = sync_playwright().start()
            self.perfil.mkdir(parents=True, exist_ok=True)
            self._ctx = self._pw.chromium.launch_persistent_context(
                str(self.perfil), channel=self.cfg.navegador, headless=False, no_viewport=True,
                args=["--start-maximized"], accept_downloads=False,
                chromium_sandbox=True,   # sem isto o Chrome mostra a faixa "--no-sandbox ... segurança afetadas"
            )
            self.page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
            self.page.set_default_timeout(30000)
            self.page.on("dialog", self._dialogo)
        except Exception as e:
            # Um Playwright que falhou ao abrir não pode ser reaproveitado (derrubava o app na 2ª tentativa)
            self.fechar()
            nome = {"chrome": "Google Chrome", "msedge": "Microsoft Edge"}.get(self.cfg.navegador, self.cfg.navegador)
            raise FalhaRobo(f"Não consegui abrir o {nome} do robô: {str(e).splitlines()[0]}") from e

    def fechar(self) -> None:
        try:
            if self._ctx:
                self._ctx.close()
        except Exception:
            pass
        finally:
            try:
                if self._pw:
                    self._pw.stop()
            except Exception:
                pass
            self._pw = self._ctx = self.page = None

    ultimo_dialogo = ""

    def _dialogo(self, d: Dialog) -> None:
        # "Deseja sair? alterações não salvas" ao sair da tela sem salvar (Pular) → aceita; qualquer outro → recusa
        if d.type == "beforeunload":
            d.accept()
        else:
            self.ultimo_dialogo = d.message
            log.warning("Diálogo inesperado do navegador recusado: %s %s", d.type, d.message)
            d.dismiss()

    def _salvar_e_esperar(self, botao, o_que: str = "", timeout_s: int = 30) -> None:
        """Clica Salvar e espera a página seguinte. Se o SGCOR recusar (aviso SweetAlert "campos obrigatórios" ou
        alert do navegador), para NA HORA com a mensagem do SGCOR, em vez de esperar o tempo todo."""
        pg = self.page
        self.ultimo_dialogo = ""
        pg.evaluate("() => { window.__autocorAntesDeSalvar = true; }")     # some quando a página seguinte abre
        botao.click()
        fim = time.monotonic() + timeout_s
        while time.monotonic() < fim:
            try:
                # 1º: a página trocou? então salvou — mesmo que a página nova mostre um aviso de "sucesso"
                if not pg.evaluate("() => window.__autocorAntesDeSalvar === true"):
                    pg.wait_for_load_state("load")
                    self.esperar_tela()
                    return
                # ainda na mesma página: aviso ou alert = o SGCOR recusou
                aviso = pg.locator(".swal2-popup:visible")
                if aviso.count():
                    texto = " ".join((aviso.first.inner_text() or "").split())
                    raise FalhaRobo(f"O SGCOR recusou salvar{o_que}: {texto}")
                if self.ultimo_dialogo:
                    raise FalhaRobo(f"O SGCOR recusou salvar{o_que}: {self.ultimo_dialogo}")
            except FalhaRobo:
                raise
            except Exception:
                pass                       # a página está trocando no meio da checagem
            pg.wait_for_timeout(200)
        raise FalhaRobo(f"O SGCOR não respondeu ao salvar{o_que} em {timeout_s} s")

    # ------------------------------------------------------------ sessão

    def ir(self, url: str, popup: bool = False, esperar: bool = True) -> None:
        """Vai para a URL. Popups (popup.php) não têm o menu com 'Sair': nelas, sessão expirada = tela de senha.
        esperar=False: não espera a rede ficar parada (≥ 0,5 s) — quem chama espera o elemento de que precisa."""
        self.abrir()
        self.page.goto(url, wait_until="load")
        if popup:
            if self.page.locator("input[type='password']").count():
                raise SessaoExpirada()
        elif not self.logado():
            raise SessaoExpirada()
        if esperar:
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

    def verificar(self, ao_esperar=None) -> bool:
        """Abre o SGCOR; se pedir login, espera o consultor entrar na janela do robô (até cfg.espera_login s)."""
        self.abrir()
        self.page.goto(url_lista(self.cfg), wait_until="domcontentloaded")
        if self.logado():
            return True
        if ao_esperar:
            ao_esperar()
        self.page.bring_to_front()
        try:
            # depois do login o SGCOR pode ir para qualquer tela; basta aparecer o menu com "Sair"
            self.page.wait_for_selector("[onclick*='logout']", state="attached",
                                        timeout=self.cfg.espera_login * 1000)
        except Exception:
            return False
        return True

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
            # pega os bytes e grava aqui: com path=, o Playwright grava via run_in_executor, que no Python 3.15
            # dentro do app falha com "'lazy_import' object is not callable"
            arq.write_bytes(self.page.screenshot(full_page=True))
            return arq
        except Exception as e:  # print não pode derrubar o lote
            log.warning("Não consegui salvar o print (%s): %s", etapa, e)
            return None

    def _guardar_html(self, caso: Caso, etapa: str, html: str) -> None:
        """Cópia local da página (diagnóstico; mesma retenção de 90 dias dos prints)."""
        try:
            pasta = self.prints / date.today().strftime("%Y%m%d")
            pasta.mkdir(parents=True, exist_ok=True)
            (pasta / f"{datetime.now():%H%M%S}_{_slug(caso.nome)}_{_slug(etapa)}.html").write_text(html, encoding="utf-8")
        except Exception as e:
            log.warning("Não consegui guardar o HTML (%s): %s", etapa, e)

    # ------------------------------------------------------------ busca

    def buscar(self, caso: Caso) -> LinhaApolice:
        """Q11/Q24/Q30. Tenta o CNPJ formatado e, sem resultado, só os dígitos."""
        linhas: list[LinhaApolice] = []
        for formatado in (True, False):
            self.ir(url_busca(self.cfg, caso.proposta.cnpj, caso.seguradora, formatado))
            html = self.page.content()
            linhas = ler_lista(html)
            if linhas:
                break
        self.print_(caso, "busca")
        self._guardar_html(caso, "busca", html)
        for l in linhas:   # diagnóstico: o que o robô viu na lista
            log.info("   linha: ID %s · apólice %s · %s a %s · nível %s · %s · %s · %s · CNPJ %s", l.proposta_id,
                     l.apolice, l.inicio, l.fim, l.nivel or "?", l.tipo or "?", l.status or "?",
                     (l.companhia or "?")[:14], l.cnpj or "?")
        linha, motivo = escolher_apolice(linhas, caso, self.cfg)
        if vale_procurar_em_outros_ramos(motivo):
            # Q71: a apólice que termina quando a nova começa pode estar em outro ramo (Caixa Aqui) ou seguradora
            log.info("%s: %s — procurando pelo CNPJ em outros ramos/seguradoras.", caso.nome, motivo)
            largas = self._buscar_so_cnpj(caso)
            linha, motivo = escolher_apolice(largas, caso, self.cfg, outros_ramos=True)
            if linha:
                log.info("%s: apólice anterior em outro ramo/seguradora: ID %s · %s · %s.", caso.nome,
                         linha.proposta_id, linha.companhia, linha.ramo)
        if motivo:
            raise FalhaRobo(motivo)
        if marca_seguradora(caso) not in linha.companhia.upper():
            # renovar de outra seguradora exige trocar a companhia na 1ª tela (ainda não mapeada) → não grava nada
            raise FalhaRobo(f"A apólice anterior (ID {linha.proposta_id}) é da {linha.companhia} e a proposta nova "
                            f"é da {caso.seguradora}: o robô ainda não troca a seguradora na 1ª tela — cadastrar à mão")
        log.info("%s: apólice anterior no SGCOR = ID %s (apólice %s, %s a %s)", caso.nome, linha.proposta_id,
                 linha.apolice, linha.inicio, linha.fim)
        return linha

    def _buscar_so_cnpj(self, caso: Caso) -> list[LinhaApolice]:
        """Pesquisa só pelo CNPJ do segurado, sem filtrar companhia nem ramo (Q71)."""
        linhas: list[LinhaApolice] = []
        for formatado in (True, False):
            self.ir(url_busca_cnpj(self.cfg, caso.proposta.cnpj, formatado))
            html = self.page.content()
            linhas = ler_lista(html)
            if linhas:
                break
        self.print_(caso, "busca_outros_ramos")
        self._guardar_html(caso, "busca_outros_ramos", html)
        for l in linhas:
            log.info("   linha: ID %s · %s a %s · nível %s · %s · %s · %s", l.proposta_id, l.inicio, l.fim,
                     l.nivel or "?", (l.companhia or "?")[:14], l.ramo or "?", l.status or "?")
        return linhas

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
                # sem digitar: o valor vai direto, já no formato do SGCOR ("3.058,54", "31/12/2026"), então as
                # máscaras de teclado não precisam agir. O Tab dispara o "sair do campo" (cálculos do SGCOR, como
                # Vigência fim e Prêmio líquido); a ordem dos campos garante que o nosso valor é o que fica, e a
                # conferência abaixo pega qualquer campo que não aceitou.
                alvo.fill(c.valor)
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

    # ------------------------------------------------------------ F3: depois da 1ª tela

    def _botao(self, texto: str):
        """Botão da barra pelo texto exato. Nas listas a barra é ul.botoesToolbar; nos formulários é uma <ul> sem
        classe dentro de #form-toolbar — por isso: qualquer li.noselect VISÍVEL com o <span> do texto."""
        return self.page.locator("li.noselect:visible").filter(
            has=self.page.locator(f"span:text-is('{texto}')")).first

    def _salvar(self):
        return self.page.locator("li#btnSalvar:visible").first

    def _swal(self, timeout_ms: int = 8000) -> str | None:
        """Texto do aviso SweetAlert2 aberto (ou None se nenhum abrir no prazo)."""
        try:
            self.page.wait_for_selector(".swal2-popup", state="visible", timeout=timeout_ms)
        except Exception:
            return None
        return (self.page.locator(".swal2-popup").inner_text() or "").strip()

    def _url_completa(self, rel: str) -> str:
        return rel if rel.startswith("http") else self.cfg.url_sgcor + rel.lstrip("/")

    def avancar(self, caso: Caso) -> str:
        """Clica Avançar na 1ª tela. A partir daqui a renovação EXISTE no SGCOR. Devolve o propostaId novo."""
        pg = self.page
        self._botao("Avançar").click()
        aviso = self._swal()
        if aviso is not None:
            if "vigência" in aviso.lower() and self.cfg.vigencia_inicio in aviso and self.cfg.vigencia_fim in aviso:
                pg.locator(".swal2-confirm").click()       # "Sim, estão corretas" (Q52)
                aviso2 = self._swal(4000)                  # p.ex. "Número máximo de parcelas…"
                if aviso2 is not None:
                    raise FalhaRobo(f"SGCOR recusou o Avançar: {aviso2}")
            else:
                raise FalhaRobo(f"Aviso inesperado ao Avançar: {aviso}")
        pg.wait_for_url(re.compile(r"op=propostasItens"), timeout=60000)
        self.esperar_tela()
        m = re.search(r"propostaId=(\d+)", pg.url)
        if not m:
            raise FalhaRobo("Avancei, mas não achei o ID da renovação na tela de Itens")
        self.print_(caso, "itens")
        log.info("%s: renovação criada no SGCOR (ID %s).", caso.nome, m.group(1))
        return m.group(1)

    def coberturas(self, caso: Caso, proposta_id: str, dic) -> None:
        """Q8/Q57: ajusta só o LMI das coberturas casadas pelo dicionário. Qualquer dúvida → FalhaRobo."""
        if not ("op=propostasItens" in self.page.url and f"propostaId={proposta_id}" in self.page.url):
            # retomada: a tela atual não é a de Itens desta renovação (logo depois do Avançar já é)
            self.ir(self._url_completa(f"?op=propostasItens&form=listar&propostaId={proposta_id}&cadastro=true"))
            self.esperar_tela()
        html_itens = self.page.content()
        itens = itens_da_proposta(html_itens, proposta_id)
        if len(itens) != 1:
            raise FalhaRobo(f"A renovação tem {len(itens)} itens; o robô só ajusta coberturas com 1 item")
        ramo = ramo_da_tela(html_itens) or ""
        outro_ramo = mudou_de_ramo(ramo, caso)       # Q71/Q73: ex.: lotérica renovando a partir de um Caixa Aqui
        url_lista_cob = self._url_completa(
            f"popup.php?op=propostasItensCoberturas&form=listar&propostaId={proposta_id}&propostaItemId={itens[0]}")
        self.ir(url_lista_cob, popup=True)
        sgcor = ler_coberturas_item(self.page.content())
        if outro_ramo:
            log.info("%s: renovação no ramo %s, diferente do da proposta: as coberturas de Incêndio e Valores que "
                     "faltarem serão incluídas.", caso.nome, ramo)
            if self._incluir_coberturas(caso, proposta_id, itens[0], sgcor, dic):
                self.ir(url_lista_cob, popup=True)
                sgcor = ler_coberturas_item(self.page.content())
        ajustes, pend, avisos = plano_coberturas(caso.coberturas, sgcor, dic, self.cfg.coberturas_ajustar)
        self.print_(caso, "coberturas_antes")
        if pend:
            raise FalhaRobo("Coberturas: " + " | ".join(pend))
        for a in avisos:
            log.info("%s: %s", caso.nome, a)
        log.info("%s: coberturas do item: %d no SGCOR, %d da proposta; %d LMI a ajustar.", caso.nome, len(sgcor),
                 len(caso.coberturas), len(ajustes))
        for a in ajustes:
            self.ir(self._url_completa(a.url_alterar), popup=True)
            tipo = self.page.locator("select[name='coberturaId']").first
            if tipo.count() and not tipo.input_value():
                # a cobertura do item não existe na lista "Cobertura" da edição (cadastro antigo com outro tipo):
                # o SGCOR não salva sem escolher uma — o robô não escolhe tipo de cobertura por conta própria
                raise FalhaRobo(f"Coberturas: “{a.nome_sgcor}” está no item, mas o campo Cobertura da edição vem "
                                f"vazio no SGCOR (tipo de cobertura que não existe na lista). Escolha a cobertura e "
                                f"ajuste o LMI à mão: {a.de} → {a.para}")
            campo = self.page.locator("input[name='importancia']").first
            campo.fill(formatar_dinheiro(a.para))      # direto, no formato do SGCOR ("30.000,00"), como no Valor Fixo
            campo.dispatch_event("change")
            if normalizar_valor(campo.input_value()) != normalizar_valor(formatar_dinheiro(a.para)):
                raise FalhaRobo(f"LMI de “{a.nome_sgcor}” não aceitou {formatar_dinheiro(a.para)}")
            self._salvar_e_esperar(self._salvar(), f" o LMI de “{a.nome_sgcor}”")
            log.info("%s: LMI de “%s” %s → %s", caso.nome, a.nome_sgcor, a.de, a.para)
        # confere a lista de novo
        self.ir(url_lista_cob, popup=True)
        depois, pend, _ = plano_coberturas(caso.coberturas, ler_coberturas_item(self.page.content()), dic,
                                          self.cfg.coberturas_ajustar)
        self.print_(caso, "coberturas_depois")
        if depois or pend:
            raise FalhaRobo("Coberturas não ficaram iguais à proposta depois de salvar")
        if outro_ramo:
            faltam = self._tipos_que_faltam(caso, ler_coberturas_item(self.page.content()), dic)
            if faltam:
                raise FalhaRobo("Coberturas incluídas não apareceram no item: " + ", ".join(faltam))

    def _tipos_que_faltam(self, caso: Caso, sgcor, dic) -> list[str]:
        no_item = {t.chave for c in sgcor if (t := dic.tipo_de(c.nome, "sgcor"))}
        return sorted({ch for _, ch in caso.coberturas if ch in self.cfg.coberturas_ajustar and ch not in no_item})

    def _incluir_coberturas(self, caso: Caso, proposta_id: str, item_id: str, sgcor, dic) -> bool:
        """Q71 (mapa §3.1): inclui de uma vez, na tabela "Novo", os tipos que faltam no item. Só digita o LMI e marca
        a linha; Salvar = submit do formulário. Devolve True se incluiu algo."""
        if not self._tipos_que_faltam(caso, sgcor, dic):
            return False
        self.ir(self._url_completa(f"popup.php?op=propostasItensCoberturas&form=cadastrar&propostaId={proposta_id}"
                                   f"&propostaItemId={item_id}"), popup=True)
        tabela = linhas_para_incluir(self.page.content())
        inclusoes, pend = plano_inclusoes(caso.coberturas, sgcor, dic, self.cfg.coberturas_ajustar,
                                          self.cfg.coberturas_incluir or INCLUIR_PADRAO, tabela)
        if pend:
            raise FalhaRobo("Coberturas: " + " | ".join(pend))
        for inc in inclusoes:
            valor = formatar_dinheiro(inc.lmi)
            campo = self.page.locator(f'input[name="dados[{inc.cobertura_id}][importancia]"]').first
            campo.fill(valor)
            self.page.locator(f"#cobertura_{inc.cobertura_id}").check()
            if normalizar_valor(campo.input_value()) != normalizar_valor(valor):
                raise FalhaRobo(f"LMI de “{inc.nome_sgcor}” não aceitou {valor}")
        self.print_(caso, "coberturas_incluir")
        # "Salvar" (salvarMultiplasCoberturas()); NUNCA "Salvar | Novo item" ('t') nem "Nova Cobertura"
        salvar = self.page.locator('li#btnSalvar[onclick*="salvarMultiplasCoberturas()"]').first
        self._salvar_e_esperar(salvar, " as coberturas incluídas", 60)
        for inc in inclusoes:
            log.info("%s: cobertura incluída: “%s” R$ %s (proposta: “%s”).", caso.nome, inc.nome_sgcor,
                     formatar_dinheiro(inc.lmi), inc.nome_proposta)
        return True

    def repasse(self, caso: Caso, proposta_id: str, produtor: str) -> None:
        """Repasse: produtor = consultor, Repasse Sobre = VF, Valor Fixo = bônus, Parcela Única →
        'Salvar e Gerar Parcelamento' (gera as parcelas)."""
        # olha a lista primeiro: numa retomada o repasse já foi copiado, e copiar de novo poderia duplicá-lo
        self.ir(self._url_completa(f"?op=repasses&form=listar&propostaId={proposta_id}&cadastro=true"))
        urls = [u for u in url_editar_repasse(self.page.content()) if f"propostaId={proposta_id}" in u]
        if not urls:
            # = Avançar da tela de Itens: copia o repasse da apólice anterior e abre a lista de repasses
            self.ir(self._url_completa(
                f"?op=propostas&form=getRepassesPropostaOriginal&cadastro=true&propostaId={proposta_id}"))
            urls = [u for u in url_editar_repasse(self.page.content()) if f"propostaId={proposta_id}" in u]
        if len(urls) != 1:
            raise FalhaRobo(f"A renovação tem {len(urls)} repasses; esperado 1")
        self.ir(self._url_completa(urls[0]))     # = lápis + "Sim" no aviso de excluir parcelas
        self.preencher_repasse(caso, produtor)
        with self.page.expect_navigation(timeout=60000):
            self._botao("Salvar e Gerar Parcelamento").click()
        self.esperar_tela()
        self.print_(caso, "repasse_salvo")
        log.info("%s: repasse salvo (%s, valor fixo R$ %s) e parcelamento gerado.", caso.nome, produtor,
                 formatar_dinheiro(caso.bonus))

    def preencher_repasse(self, caso: Caso, produtor: str) -> None:
        """Formulário do repasse (sem salvar). Ordem importa: produtor → forma → Repasse Sobre → Valor Fixo."""
        pg = self.page
        forma = pg.locator("#repasseForma")
        forma_copiada = forma.input_value()      # a que veio copiada da apólice anterior (ex.: NP)
        atual = (pg.locator("#produtorId option:checked").text_content() or "").strip()
        if atual != produtor:
            # trocar o produtor dispara getInfoProdutor(): um AJAX que LIMPA o repasse e recarrega os padrões do
            # produtor. Espera a resposta antes de mexer no resto.
            with pg.expect_response(lambda r: "acao=getRepasse" in r.url, timeout=30000):
                pg.locator("#produtorId").select_option(label=produtor)
            pg.wait_for_timeout(500)                # o callback do AJAX preenche os campos logo depois
            log.info("%s: produtor do repasse trocado de “%s” para “%s”.", caso.nome, atual, produtor)
        if not forma.input_value():
            if not forma_copiada:
                raise FalhaRobo("Forma de Repasse veio vazia no SGCOR")
            # trocar a forma ESVAZIA "Repasse Sobre" e recarrega as opções por outro AJAX (getRepassesSobre)
            with pg.expect_response(lambda r: "acao=getRepassesSobre" in r.url, timeout=30000):
                forma.select_option(forma_copiada, force=True)
            pg.wait_for_function("() => [...document.querySelectorAll('#repasseSobre option')]"
                                 ".some(o => o.value === 'VF')", timeout=15000)
            log.info("%s: Forma de Repasse mantida (%s).", caso.nome, forma_copiada)
        if pg.locator("#repasseSobre").input_value() != "VF":
            pg.locator("#repasseSobre").select_option("VF", force=True)
            pg.wait_for_timeout(300)
        valor = pg.locator("#valorFixo")
        valor.wait_for(state="visible")
        # a máscara do SGCOR (MascaraValorMonetario) reage a cada tecla e brigava com a digitação;
        # o valor vai direto, no mesmo formato que o próprio SGCOR usa ("40,00")
        valor.fill(formatar_dinheiro(caso.bonus))
        valor.dispatch_event("change")
        pg.locator("#radio_definirParcelasVF_0").check()   # Parcela Única
        if not forma.input_value() or pg.locator("#repasseSobre").input_value() != "VF":
            raise FalhaRobo("Forma de Repasse/Repasse Sobre não ficaram preenchidos")
        if normalizar_valor(valor.input_value()) != normalizar_valor(formatar_dinheiro(caso.bonus)):
            raise FalhaRobo(f"Valor Fixo não aceitou {formatar_dinheiro(caso.bonus)}")
        self.print_(caso, "repasse_preenchido")

    def parcelas(self, caso: Caso, proposta_id: str) -> None:
        self.ir(self._url_completa(f"?op=parcelasCompletas&form=listar&propostaId={proposta_id}&cadastro=true"))
        ps = ler_parcelas(self.page.content())
        self.print_(caso, "parcelas")
        erros = conferir_parcelas(ps, caso, self.cfg)
        if erros:
            raise FalhaRobo("Parcelas: " + " | ".join(erros))
        log.info("%s: %d parcelas conferidas (1º vencimento %s).", caso.nome, len(ps), ps[0].vencimento)

    def anexos(self, caso: Caso, proposta_id: str) -> None:
        """ACORDO + PROPOSTA (Q14/Q16): só Descrição + arquivo; não reenvia o que já existe."""
        lista = self._url_completa(f"popup.php?op=anexos&form=listar&propostaId={proposta_id}")
        self.ir(lista, popup=True)
        ja = anexos_existentes(self.page.content())
        arquivos = [("ACORDO", caso.acordo), ("PROPOSTA", caso.proposta_escolhida or caso.propostas[0])]
        for descricao, arq in arquivos:
            if descricao in ja:
                log.info("%s: anexo %s já existe — não reenviado.", caso.nome, descricao)
                continue
            if arq.stat().st_size > 10 * 1024 * 1024:
                raise FalhaRobo(f"{arq.name} tem mais de 10 MB (limite do SGCOR)")
            t0 = time.monotonic()
            # anexos mais rápidos: o formulário só precisa da Descrição e do arquivo, então espera o campo aparecer
            # em vez de a rede ficar parada; e depois de salvar não espera a página assentar, porque o próximo passo
            # já abre outra página. A lista do fim (com espera completa) confere que os dois anexos estão lá.
            self.ir(self._url_completa(f"popup.php?op=anexos&form=cadastrar&propostaId={proposta_id}"), popup=True,
                    esperar=False)
            campo = self.page.locator("input[name='descricao']").first
            campo.wait_for(state="visible")
            campo.fill(descricao)
            self.page.locator("input[type='file'][name='arquivo']").first.set_input_files(str(arq))
            with self.page.expect_navigation(timeout=60000):
                self._salvar().click()
            log.info("%s: anexo %s enviado (%s) em %.1f s.", caso.nome, descricao, arq.name, time.monotonic() - t0)
        self.ir(lista, popup=True)
        faltando = {"ACORDO", "PROPOSTA"} - anexos_existentes(self.page.content())
        self.print_(caso, "anexos")
        if faltando:
            raise FalhaRobo(f"Anexo(s) não apareceram na lista: {', '.join(sorted(faltando))}")
