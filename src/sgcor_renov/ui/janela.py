"""Janela principal: pastas, tabela de lotéricas, detalhe/resolução de pendências e execução com confirmação.

Nada é enviado ao SGCOR sem o consultor marcar as lotéricas, clicar em Executar e confirmar o resumo (Q33).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QSplitter, QTableView,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..config import carregar
from ..estado import Ajuste, Estado
from ..modelos import Caso
from ..numeros import formatar_cnpj, formatar_dinheiro
from .cadastradas import JanelaCadastradas
from .leitor import Leitor
from .tabela import FORMAS, FiltroCasos, ModeloCasos
from .trabalhador import Trabalhador
from .tutorial import Tutorial

NOME = "AutoCOR"
ORG, APP = "GrupoProtege", "SGCOR-Renovacoes"   # identificadores internos (registro/estado): não mudam com o nome
RECURSOS = Path(__file__).parent / "recursos"
AZUL = "#12284F"          # azul-marinho da logo do Grupo Protege
ESTILO = f"""
#cabecalho {{ background: {AZUL}; }}
#cabecalho QLabel {{ color: white; }}
#titulo {{ font-size: 17px; font-weight: 600; }}
#cabecalho QPushButton {{ color: white; background: transparent; border: 1px solid #5b74a3; border-radius: 4px;
                          padding: 4px 12px; }}
#cabecalho QPushButton:hover {{ background: #1d3a6e; }}
QPushButton#primario {{ background: {AZUL}; color: white; border: 1px solid #2c4c86; border-radius: 4px;
                        padding: 6px 22px; font-weight: 600; }}
QPushButton#primario:hover {{ background: #1d3a6e; }}
QPushButton#primario:pressed {{ background: #0b1a36; }}
QPushButton#primario:disabled {{ background: #9aa5b8; color: #eef1f5; }}
"""


def abrir_no_windows(caminho: Path) -> None:
    if sys.platform == "win32":
        os.startfile(caminho)  # noqa: S606 — abre pasta/PDF local escolhido pelo próprio consultor


class Janela(QMainWindow):
    pedir_leitura = Signal(object, object)   # raízes, ajustes

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{NOME} — renovações lotéricas → SGCOR")
        self.resize(1400, 820)
        self.cfg = carregar()
        self.estado = Estado()
        self.settings = QSettings()   # usa ORG/APP do QApplication e o formato padrão (registro; arquivo nos testes)
        self.lendo = False
        self.reler_depois = False
        self.conectado = False
        self.executando = False

        self._montar()
        self._iniciar_leitor()
        self._iniciar_robo()
        self._iniciar_observador()
        QTimer.singleShot(0, self._inicio)

    # ------------------------------------------------------------------ montagem

    def _montar(self) -> None:
        central = QWidget()
        externo = QVBoxLayout(central)
        externo.setContentsMargins(0, 0, 0, 0)
        externo.setSpacing(0)

        # faixa com a identidade do Grupo Protege
        cabecalho = QFrame()
        cabecalho.setObjectName("cabecalho")
        cl = QHBoxLayout(cabecalho)
        cl.setContentsMargins(16, 10, 20, 10)
        logo = QLabel()
        logo.setPixmap(QPixmap(str(RECURSOS / "logo-protege.png")).scaledToHeight(44, Qt.SmoothTransformation))
        cl.addWidget(logo)
        cl.addStretch(1)
        titulo = QLabel(f"{NOME}<br><span style='font-size: 12px; font-weight: 400;'>renovações lotéricas → SGCOR"
                        f"</span>")
        titulo.setObjectName("titulo")
        titulo.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        cl.addWidget(titulo)
        cl.addSpacing(16)
        bt_tutorial = QPushButton("Como usar")
        bt_tutorial.setToolTip("Abre o tutorial: como organizar as pastas e usar o robô")
        bt_tutorial.clicked.connect(self.mostrar_tutorial)
        cl.addWidget(bt_tutorial)
        externo.addWidget(cabecalho)

        corpo = QWidget()
        raiz = QVBoxLayout(corpo)
        externo.addWidget(corpo, 1)

        # pastas + consultor
        topo = QGridLayout()
        docs = Path.home() / "Documents"
        self.ed_porto = self._campo_pasta(topo, 0, "Pasta PORTO", "porto", docs / "FECHADOS PORTO")
        self.ed_tokio = self._campo_pasta(topo, 1, "Pasta TOKIO", "tokio", docs / "FECHADOS TOKIO")
        topo.addWidget(QLabel("Consultor / Produtor"), 0, 3)
        self.ed_consultor = QComboBox()        # lista lida do SGCOR (Q36)
        self.ed_consultor.setMinimumWidth(260)
        salvo = self.settings.value("consultor", "")
        if salvo:
            self.ed_consultor.addItem(salvo)
        self.ed_consultor.setPlaceholderText("clique em Verificar conexão para carregar")
        self.ed_consultor.currentTextChanged.connect(lambda t: t and self.settings.setValue("consultor", t))
        topo.addWidget(self.ed_consultor, 0, 4)
        self.bt_sgcor = QPushButton("Verificar conexão ao SGCOR")
        self.bt_sgcor.setToolTip("Abre o navegador do robô. Se pedir login, entre com o seu usuário nele e clique de novo.")
        self.bt_sgcor.clicked.connect(self._verificar)
        topo.addWidget(self.bt_sgcor, 1, 4)
        self.lb_conexao = QLabel("● SGCOR não verificado")
        self.lb_conexao.setStyleSheet("color: #888;")
        topo.addWidget(self.lb_conexao, 1, 3)
        topo.setColumnStretch(1, 1)
        raiz.addLayout(topo)

        # filtros
        filtros = QHBoxLayout()
        self.grupo_filtro = QButtonGroup(self)
        self.bt_filtros = {}
        for chave, rotulo in (("", "Todas"), ("Pronto", "Prontas"), ("Pendente", "Pendentes")):
            b = QPushButton(rotulo)
            b.setCheckable(True)
            b.setChecked(chave == "")
            b.clicked.connect(lambda _=False, k=chave: self.filtro.definir(status=k))
            self.grupo_filtro.addButton(b)
            self.bt_filtros[chave] = b
            filtros.addWidget(b)
        filtros.addSpacing(16)
        self.ed_busca = QLineEdit()
        self.ed_busca.setPlaceholderText("Buscar lotérica, CNPJ ou apólice…")
        self.ed_busca.textChanged.connect(lambda t: self.filtro.definir(texto=t))
        filtros.addWidget(self.ed_busca, 1)
        bt_todos = QPushButton("Marcar prontas visíveis")
        bt_todos.clicked.connect(lambda: self.modelo.marcar_todos(self._visiveis(), True))
        bt_nenhum = QPushButton("Desmarcar")
        bt_nenhum.clicked.connect(lambda: self.modelo.marcar_todos(self.modelo.casos, False))
        bt_ler = QPushButton("Ler pastas agora")
        bt_ler.clicked.connect(self.ler)
        self.bt_cadastradas = QPushButton("Ver cadastradas")
        self.bt_cadastradas.setToolTip("Lotéricas já cadastradas (pastas em _CADASTRADOS), com o ID do SGCOR")
        self.bt_cadastradas.clicked.connect(self._ver_cadastradas)
        for b in (bt_todos, bt_nenhum, bt_ler):
            filtros.addWidget(b)
        filtros.addSpacing(16)
        filtros.addWidget(self.bt_cadastradas)
        raiz.addLayout(filtros)

        # tabela | detalhe
        self.modelo = ModeloCasos()
        self.filtro = FiltroCasos()
        self.filtro.setSourceModel(self.modelo)
        self.modelo.dataChanged.connect(lambda *_: self._atualizar_rodape())
        self.tabela = QTableView()
        self.tabela.setModel(self.filtro)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setAlternatingRowColors(True)
        cab = self.tabela.horizontalHeader()
        cab.setSectionResizeMode(QHeaderView.ResizeToContents)
        cab.setSectionResizeMode(3, QHeaderView.Stretch)
        self.tabela.selectionModel().currentRowChanged.connect(lambda cur, _: self._mostrar(cur))

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.tabela)
        split.addWidget(self._painel_detalhe())
        split.setSizes([950, 450])
        raiz.addWidget(split, 1)

        # rodapé: modo + executar
        rodape = QHBoxLayout()
        rodape.addWidget(QLabel("Modo:"))
        self.cb_modo = QComboBox()
        self.cb_modo.addItem("Automático — faz tudo; só para em pendência", "automatico")
        self.cb_modo.addItem("Conferência — para na 1ª tela para você conferir", "conferencia")
        rodape.addWidget(self.cb_modo)
        rodape.addStretch(1)
        self.lb_contagem = QLabel()
        self.lb_contagem.setMinimumWidth(140)
        self.lb_contagem.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        rodape.addWidget(self.lb_contagem)
        self.bt_pausar = QPushButton("Pausar")
        self.bt_pausar.setToolTip("Termina a lotérica em andamento e para (Q47)")
        self.bt_pausar.setEnabled(False)
        self.bt_pausar.clicked.connect(self._pausar)
        rodape.addWidget(self.bt_pausar)
        self.bt_executar = QPushButton("Executar selecionadas")
        self.bt_executar.setObjectName("primario")
        self.bt_executar.setMinimumHeight(34)
        self.bt_executar.clicked.connect(self.executar)
        rodape.addWidget(self.bt_executar)
        raiz.addLayout(rodape)

        # barra de conferência (aparece quando o robô preencheu a 1ª tela e está esperando)
        self.barra_conf = QFrame()
        self.barra_conf.setStyleSheet("QFrame { background: #3a2f00; border: 1px solid #d4a300; border-radius: 4px; }"
                                      "QLabel { color: #ffd54a; border: none; }")
        bl = QHBoxLayout(self.barra_conf)
        self.lb_conf = QLabel()
        self.lb_conf.setWordWrap(True)
        bl.addWidget(self.lb_conf, 1)
        self.bt_continuar = QPushButton("Continuar (grava)")
        self.bt_continuar.setToolTip("O robô clica Avançar e faz coberturas, repasse, parcelas e anexos")
        self.bt_pular = QPushButton("Pular lotérica (não grava)")
        self.bt_parar = QPushButton("Parar lote")
        self.bt_retomar = QPushButton("Retomar")
        self.bt_continuar.clicked.connect(lambda: self._decidir("continuar"))
        self.bt_pular.clicked.connect(lambda: self._decidir("pular"))
        self.bt_parar.clicked.connect(lambda: (self.trab.pedir_parada(), self.barra_conf.setVisible(False)))
        self.bt_retomar.clicked.connect(lambda: self._decidir("retomar"))
        for b in (self.bt_continuar, self.bt_pular, self.bt_retomar, self.bt_parar):
            bl.addWidget(b)
        self.barra_conf.setVisible(False)
        raiz.addWidget(self.barra_conf)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        self.log.setPlaceholderText("Log do robô")
        raiz.addWidget(self.log)

        self.setCentralWidget(central)
        self.progresso = QProgressBar()
        self.progresso.setMaximumWidth(260)
        self.progresso.setVisible(False)
        self.statusBar().addPermanentWidget(self.progresso)

    def _inicio(self) -> None:
        """Ao abrir: tutorial primeiro (a menos que o consultor tenha desligado), depois a leitura das pastas."""
        if not self.settings.value("tutorial_ocultar", False, type=bool):
            self.mostrar_tutorial()
        self.ler()

    def mostrar_tutorial(self) -> None:
        dlg = Tutorial(self, RECURSOS / "logo-protege.png", self.settings.value("tutorial_ocultar", False, type=bool))
        dlg.exec()
        self.settings.setValue("tutorial_ocultar", dlg.ck_ocultar.isChecked())

    def _campo_pasta(self, grade: QGridLayout, linha: int, rotulo: str, chave: str, padrao: Path) -> QLineEdit:
        grade.addWidget(QLabel(rotulo), linha, 0)
        ed = QLineEdit(self.settings.value(f"pasta_{chave}", str(padrao) if padrao.is_dir() else ""))
        ed.setReadOnly(True)
        grade.addWidget(ed, linha, 1)
        bt = QPushButton("Selecionar…")

        def escolher():
            d = QFileDialog.getExistingDirectory(self, rotulo, ed.text() or str(Path.home()))
            if d:
                ed.setText(d)
                self.settings.setValue(f"pasta_{chave}", d)
                self._iniciar_observador()
                self.ler()
        bt.clicked.connect(escolher)
        grade.addWidget(bt, linha, 2)
        return ed

    def _painel_detalhe(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.lb_titulo = QLabel("Selecione uma lotérica")
        self.lb_titulo.setStyleSheet("font-size: 15px; font-weight: 600;")
        self.lb_titulo.setWordWrap(True)
        lay.addWidget(self.lb_titulo)

        self.form_info = QFormLayout()
        self.info: dict[str, QLabel] = {}
        for k in ("Seguradora", "CNPJ", "Apólice anterior", "Proposta nº", "Vigência", "Parcelas / forma",
                  "Cobrança SGCOR", "Prêmio líquido", "IOF", "Prêmio total", "Comissão → bônus"):
            lb = QLabel("—")
            lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.info[k] = lb
            self.form_info.addRow(k + ":", lb)
        lay.addLayout(self.form_info)

        self.lb_combinado = QLabel()
        self.lb_combinado.setWordWrap(True)
        self.lb_combinado.setStyleSheet("color: #444; font-style: italic;")
        lay.addWidget(self.lb_combinado)

        lay.addWidget(QLabel("Pendências"))
        self.ls_pend = QListWidget()
        self.ls_pend.setMaximumHeight(110)
        self.ls_pend.setWordWrap(True)
        lay.addWidget(self.ls_pend)
        lay.addWidget(QLabel("Avisos"))
        self.ls_avisos = QListWidget()
        self.ls_avisos.setMaximumHeight(110)
        self.ls_avisos.setWordWrap(True)
        lay.addWidget(self.ls_avisos)
        lay.addWidget(QLabel("Coberturas da proposta (LMI)"))
        self.ls_cob = QListWidget()
        self.ls_cob.setMaximumHeight(130)
        lay.addWidget(self.ls_cob)

        box = QGroupBox("Resolver (o que o consultor confirmou)")
        f = QFormLayout(box)
        self.sp_parcelas = QSpinBox()
        self.sp_parcelas.setRange(0, 12)
        self.sp_parcelas.setSpecialValueText("— do acordo —")
        f.addRow("Parcelas:", self.sp_parcelas)
        self.cb_forma = QComboBox()
        self.cb_forma.addItem("— do acordo —", None)
        for k, v in FORMAS.items():
            self.cb_forma.addItem(v, k)
        f.addRow("Forma:", self.cb_forma)
        self.cb_proposta = QComboBox()
        f.addRow("Proposta final:", self.cb_proposta)
        botoes = QHBoxLayout()
        self.bt_aplicar = QPushButton("Aplicar")
        self.bt_aplicar.clicked.connect(self._aplicar_ajuste)
        self.bt_desfazer = QPushButton("Desfazer ajuste")
        self.bt_desfazer.clicked.connect(lambda: self._salvar_ajuste(Ajuste()))
        botoes.addWidget(self.bt_aplicar)
        botoes.addWidget(self.bt_desfazer)
        f.addRow(botoes)
        lay.addWidget(box)

        abrir = QHBoxLayout()
        self.bt_pasta = QPushButton("Abrir pasta")
        self.bt_acordo = QPushButton("Abrir acordo")
        self.bt_prop = QPushButton("Abrir proposta")
        for b in (self.bt_pasta, self.bt_acordo, self.bt_prop):
            abrir.addWidget(b)
        self.bt_pasta.clicked.connect(lambda: self._atual and abrir_no_windows(
            self._atual.pasta if self._atual.pasta.is_dir() else self._atual.pasta.parent))
        self.bt_acordo.clicked.connect(lambda: self._atual and self._atual.acordo and abrir_no_windows(self._atual.acordo))
        self.bt_prop.clicked.connect(lambda: self._atual and self._abrir_proposta())
        lay.addLayout(abrir)
        lay.addStretch(1)
        self._atual: Caso | None = None
        self._habilitar_detalhe(False)
        return w

    # ------------------------------------------------------------------ leitura

    def _iniciar_leitor(self) -> None:
        self.thread = QThread(self)
        self.leitor = Leitor(self.cfg)
        self.leitor.moveToThread(self.thread)
        self.pedir_leitura.connect(self.leitor.ler)
        self.leitor.progresso.connect(self._progresso)
        self.leitor.concluido.connect(self._lido)
        self.leitor.erro.connect(self._erro_leitura)
        self.thread.start()

    def _raizes(self) -> list[Path]:
        return [Path(e.text()) for e in (self.ed_porto, self.ed_tokio) if e.text()]

    def ler(self) -> None:
        if self.lendo:
            self.reler_depois = True
            return
        raizes = [r for r in self._raizes() if r.is_dir()]
        if not raizes:
            self.statusBar().showMessage("Selecione as pastas FECHADOS PORTO e FECHADOS TOKIO.")
            return
        ajustes = {}
        for raiz in raizes:
            for p in raiz.iterdir():
                if p.is_dir() and (a := self.estado.ajuste(p)):
                    ajustes[p] = a
        self.lendo = True
        self.progresso.setVisible(True)
        self.pedir_leitura.emit(raizes, ajustes)

    def _progresso(self, i: int, n: int, nome: str) -> None:
        self.progresso.setMaximum(n)
        self.progresso.setValue(i)
        self.statusBar().showMessage(f"Lendo {i}/{n}: {nome}")

    def _lido(self, casos: list[Caso]) -> None:
        selecionada = self._atual.pasta if self._atual else None
        self.modelo.definir(casos)
        self.tabela.resizeColumnsToContents()
        self.lendo = False
        self.progresso.setVisible(False)
        self._atualizar_rodape()
        self.statusBar().showMessage("Pastas lidas. Nada foi enviado ao SGCOR.", 8000)
        if selecionada:
            self._selecionar(selecionada)
        if self.reler_depois:
            self.reler_depois = False
            self.ler()

    def _erro_leitura(self, msg: str) -> None:
        self.lendo = False
        self.progresso.setVisible(False)
        QMessageBox.warning(self, "Erro ao ler as pastas", msg)

    def _iniciar_observador(self) -> None:
        """Lê de novo quando um PDF/pasta aparece, some ou muda (sem refresh manual)."""
        if hasattr(self, "watcher"):
            self.watcher.deleteLater()
        self.watcher = QFileSystemWatcher(self)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(2000)
        self.debounce.timeout.connect(self._mudou)
        self.watcher.directoryChanged.connect(lambda _: self.debounce.start())
        self._observar()

    def _observar(self) -> None:
        caminhos = []
        for raiz in self._raizes():
            if raiz.is_dir():
                caminhos.append(str(raiz))
                caminhos += [str(p) for p in raiz.iterdir() if p.is_dir()]
        atuais = set(self.watcher.directories())
        novos = [c for c in caminhos if c not in atuais]
        if novos:
            self.watcher.addPaths(novos)

    def _mudou(self) -> None:
        self._observar()
        self.ler()

    # ------------------------------------------------------------------ detalhe

    def _visiveis(self) -> list[Caso]:
        return [self.filtro.index(r, 0).data(Qt.UserRole) for r in range(self.filtro.rowCount())]

    def _selecionar(self, pasta: Path) -> None:
        for r in range(self.filtro.rowCount()):
            c = self.filtro.index(r, 0).data(Qt.UserRole)
            if c.pasta == pasta:
                self.tabela.selectRow(r)
                self._mostrar(self.filtro.index(r, 0))
                return

    def _habilitar_detalhe(self, sim: bool) -> None:
        for wdg in (self.sp_parcelas, self.cb_forma, self.cb_proposta, self.bt_aplicar, self.bt_desfazer,
                    self.bt_pasta, self.bt_acordo, self.bt_prop):
            wdg.setEnabled(sim)

    def _mostrar(self, idx) -> None:
        c: Caso | None = idx.data(Qt.UserRole) if idx.isValid() else None
        self._atual = c
        self._habilitar_detalhe(c is not None)
        if c is None:
            return
        p = c.proposta
        self.lb_titulo.setText(f"{c.nome}  ·  {c.status}")
        vals = {
            "Seguradora": c.seguradora.title(),
            "CNPJ": formatar_cnpj(p.cnpj) if p else "",
            "Apólice anterior": (p.apolice_anterior or "") if p else "",
            "Proposta nº": (p.numero or "") if p else "",
            "Vigência": f"{self.cfg.vigencia_inicio} a {self.cfg.vigencia_fim} (configuração)",
            "Parcelas / forma": f"{c.parcelas or '?'}x · {FORMAS.get(c.forma or '', c.forma or '?')}",
            "Cobrança SGCOR": str(c.cobranca_id or ""),
            "Prêmio líquido": formatar_dinheiro(c.premio_liquido),
            "IOF": formatar_dinheiro(c.iof),
            "Prêmio total": formatar_dinheiro(c.premio_total),
            "Comissão → bônus": (f"{p.comissao}% → R$ {formatar_dinheiro(c.bonus)}"
                                 if p and p.comissao is not None else ""),
        }
        for k, v in vals.items():
            self.info[k].setText(v or "—")
        e = c.escolha
        self.lb_combinado.setText(f"No acordo: “{e.trecho_parcelas}”" if e and e.trecho_parcelas else "")
        self.ls_pend.clear()
        for t in c.pendencias:
            it = QListWidgetItem("⚠ " + t)
            it.setForeground(QColor("#f0533f"))
            self.ls_pend.addItem(it)
        self.ls_avisos.clear()
        self.ls_avisos.addItems(c.avisos)
        self.ls_cob.clear()
        for cob, chave in c.coberturas:
            it = QListWidgetItem(f"R$ {formatar_dinheiro(cob.lmi):>12}   {cob.nome}" + ("" if chave else "   ⚠ sem equivalência"))
            if not chave:
                it.setForeground(QColor("#f0533f"))
            self.ls_cob.addItem(it)

        a = self.estado.ajuste(c.pasta) if c.pasta.is_dir() else None
        self.sp_parcelas.setValue((a.parcelas or 0) if a else 0)
        i = self.cb_forma.findData(a.forma if a else None)
        self.cb_forma.setCurrentIndex(max(i, 0))
        self.cb_proposta.clear()
        self.cb_proposta.addItem("—", None)
        for pr in c.propostas:
            self.cb_proposta.addItem(pr.name, pr.name)
        self.cb_proposta.setEnabled(len(c.propostas) > 1)
        if a and a.proposta:
            self.cb_proposta.setCurrentIndex(max(self.cb_proposta.findData(a.proposta), 0))
        resolvivel = c.pasta.is_dir()
        for wdg in (self.sp_parcelas, self.cb_forma, self.bt_aplicar, self.bt_desfazer):
            wdg.setEnabled(resolvivel)
        self.bt_acordo.setEnabled(c.acordo is not None)
        self.bt_prop.setEnabled(bool(c.propostas))

    def _abrir_proposta(self) -> None:
        c = self._atual
        alvo = c.proposta_escolhida or (c.propostas[0] if c.propostas else None)
        if alvo:
            abrir_no_windows(alvo)

    def _aplicar_ajuste(self) -> None:
        self._salvar_ajuste(Ajuste(
            parcelas=self.sp_parcelas.value() or None,
            forma=self.cb_forma.currentData(),
            proposta=self.cb_proposta.currentData(),
        ))

    def _salvar_ajuste(self, a: Ajuste) -> None:
        if not self._atual or not self._atual.pasta.is_dir():
            return
        self.estado.salvar(self._atual.pasta, a)
        self.ler()

    # ------------------------------------------------------------------ execução

    def _atualizar_rodape(self) -> None:
        casos = self.modelo.casos
        prontos = sum(1 for c in casos if c.status == "Pronto")
        self.bt_filtros[""].setText(f"Todas ({len(casos)})")
        self.bt_filtros["Pronto"].setText(f"Prontas ({prontos})")
        self.bt_filtros["Pendente"].setText(f"Pendentes ({len(casos) - prontos})")
        n = len(self.modelo.selecionados())
        self.lb_contagem.setText(f"{n} selecionada(s)")
        self.bt_executar.setEnabled(n > 0 and not self.executando)
        cad = sum(1 for r in self._raizes() if (r / "_CADASTRADOS").is_dir()
                  for p in (r / "_CADASTRADOS").iterdir() if p.is_dir())
        self.bt_cadastradas.setText(f"Ver cadastradas ({cad})")

    def _ver_cadastradas(self) -> None:
        JanelaCadastradas(self, [r for r in self._raizes() if r.is_dir()], self.estado, abrir_no_windows).exec()

    # ------------------------------------------------------------------ robô

    def _iniciar_robo(self) -> None:
        # o robô tem uma thread Python própria (ver trabalhador.py); os sinais chegam aqui pela fila do Qt
        self.trab = Trabalhador(self.cfg)
        fila = Qt.QueuedConnection
        self.trab.linha_log.connect(self.log.appendPlainText, fila)
        self.trab.conexao.connect(self._conexao, fila)
        self.trab.esperando_login.connect(self._esperando_login, fila)
        self.trab.situacao.connect(self._situacao, fila)
        self.trab.aguardando.connect(self._aguardando, fila)
        self.trab.login_necessario.connect(self._login_necessario, fila)
        self.trab.pausado.connect(self._pausado, fila)
        self.trab.fim_lote.connect(self._fim_lote, fila)

    def _verificar(self) -> None:
        self.bt_sgcor.setEnabled(False)
        self.lb_conexao.setText("● verificando…")
        self.lb_conexao.setStyleSheet("color: #888;")
        self.trab.pedir_verificacao()

    def _esperando_login(self) -> None:
        self.lb_conexao.setText("● faça o login na janela do robô (Chrome) — conecta sozinho")
        self.lb_conexao.setStyleSheet("color: #d4a300; font-weight: 600;")

    def _conexao(self, ok: bool, produtores: list) -> None:
        self.bt_sgcor.setEnabled(not self.executando)
        self.conectado = ok
        if ok:
            self.lb_conexao.setText("● SGCOR conectado")
            self.lb_conexao.setStyleSheet("color: #2ea043; font-weight: 600;")
            atual = self.ed_consultor.currentText()
            self.ed_consultor.blockSignals(True)
            self.ed_consultor.clear()
            self.ed_consultor.addItems([nome for _, nome in produtores])
            self.ed_consultor.blockSignals(False)
            i = self.ed_consultor.findText(atual)
            self.ed_consultor.setCurrentIndex(i if i >= 0 else -1)
        else:
            self.lb_conexao.setText("● não conectado — veja o log abaixo e clique em Verificar de novo")
            self.lb_conexao.setStyleSheet("color: #f0533f; font-weight: 600;")

    def executar(self) -> None:
        sel = self.modelo.selecionados()
        if not sel or self.executando:
            return
        if not self.conectado:
            QMessageBox.information(self, "SGCOR", "Clique em “Verificar conexão ao SGCOR” e faça o login na janela "
                                                   "do robô antes de executar.")
            return
        produtor = self.ed_consultor.currentText().strip()
        if not produtor or self.ed_consultor.findText(produtor) < 0:
            QMessageBox.information(self, "Consultor", "Escolha o seu nome na lista de produtores do SGCOR.")
            return
        dlg = Confirmacao(self, sel, self.cb_modo.currentText(), produtor)
        if dlg.exec() != QDialog.Accepted:
            self.statusBar().showMessage("Execução cancelada. Nada foi enviado ao SGCOR.", 8000)
            return
        self.executando = True
        self.bt_executar.setEnabled(False)
        self.bt_sgcor.setEnabled(False)
        self.bt_pausar.setEnabled(True)
        self.trab.pedir_execucao(sel, produtor, self.cb_modo.currentData())

    def _decidir(self, acao: str) -> None:
        self.barra_conf.setVisible(False)
        self.trab.decidir(acao)

    def _pausar(self) -> None:
        self.trab.pausa.set()
        self.bt_pausar.setEnabled(False)
        self.statusBar().showMessage("Pausa pedida: o robô para ao terminar a lotérica atual.", 8000)

    def _situacao(self, pasta: Path, texto: str) -> None:
        self.modelo.definir_situacao(pasta, texto)
        if self._atual and self._atual.pasta == pasta:
            self.lb_titulo.setText(f"{self._atual.nome}  ·  {texto}")

    def _aguardando(self, caso: Caso, campos: list) -> None:
        self._selecionar(caso.pasta)
        self.lb_conf.setText(f"<b>{caso.nome}</b>: a 1ª tela foi preenchida na janela do robô. Confira (pode corrigir "
                             f"algum campo lá mesmo). <b>Continuar</b> grava e o robô termina sozinho; "
                             f"<b>Pular</b> não grava nada.")
        self.bt_continuar.setVisible(True)
        self.bt_pular.setVisible(True)
        self.bt_retomar.setVisible(False)
        self.barra_conf.setVisible(True)
        QApplication.alert(self)

    def _login_necessario(self) -> None:
        self.lb_conf.setText("O SGCOR pediu login. Entre com o seu usuário na janela do robô e clique em Retomar.")
        self.bt_continuar.setVisible(False)
        self.bt_pular.setVisible(False)
        self.bt_retomar.setVisible(True)
        self.barra_conf.setVisible(True)
        QApplication.alert(self)

    def _pausado(self, sim: bool) -> None:
        if sim:
            self.lb_conf.setText("Lote pausado.")
            self.bt_continuar.setVisible(False)
            self.bt_pular.setVisible(False)
            self.bt_retomar.setText("Continuar o lote")
            self.bt_retomar.setVisible(True)
            self.barra_conf.setVisible(True)
        else:
            self.bt_retomar.setText("Retomar")
            self.bt_pausar.setEnabled(True)

    def _fim_lote(self, resumo: str) -> None:
        self.executando = False
        self.barra_conf.setVisible(False)
        self.bt_pausar.setEnabled(False)
        self.bt_sgcor.setEnabled(True)
        self._atualizar_rodape()
        self.statusBar().showMessage(resumo, 15000)
        QApplication.alert(self)
        if getattr(self, "fechar_ao_terminar", False):
            self.close()
        else:
            self.ler()   # lotéricas cadastradas saíram da pasta (foram para _CADASTRADOS)

    def closeEvent(self, ev):
        if self.executando:
            r = QMessageBox.question(
                self, "Lote em andamento",
                "Há um lote em andamento.\n\nParar e fechar? O robô termina a lotérica que está fazendo "
                "(para não deixar renovação pela metade no SGCOR) e o app fecha em seguida.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r == QMessageBox.Yes:
                self.fechar_ao_terminar = True
                self.barra_conf.setVisible(False)
                self.trab.pedir_parada()
                self.statusBar().showMessage("Terminando a lotérica atual; o app fecha em seguida…")
            ev.ignore()
            return
        self.leitor.cancelar.set()
        self.thread.quit()
        self.thread.wait(15000)
        # o Playwright só pode ser fechado na thread em que foi aberto: ela mesma para o lote (se houver),
        # fecha o navegador e termina
        self.trab.finalizar(espera_s=30)
        self.estado.fechar()
        super().closeEvent(ev)


class Confirmacao(QDialog):
    """Resumo do que será cadastrado; só segue com 'Confirmar'."""

    def __init__(self, pai, casos: list[Caso], modo: str, consultor: str):
        super().__init__(pai)
        self.setWindowTitle("Confirmar cadastro no SGCOR")
        self.resize(980, 480)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"<b>{len(casos)} lotérica(s)</b> · modo: {modo} · produtor: {consultor}"))
        t = QTableWidget(len(casos), 8)
        t.setHorizontalHeaderLabels(["Seguradora", "Lotérica", "Apólice anterior", "Proposta nº", "Parcelas",
                                     "Forma", "Prêmio total", "Bônus"])
        for r, c in enumerate(casos):
            p = c.proposta
            for col, v in enumerate([c.seguradora.title(), c.nome, p.apolice_anterior or "", p.numero or "",
                                     f"{c.parcelas}x", FORMAS.get(c.forma, c.forma), formatar_dinheiro(c.premio_total),
                                     formatar_dinheiro(c.bonus)]):
                t.setItem(r, col, QTableWidgetItem(v))
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lay.addWidget(t)
        linha = QFrame()
        linha.setFrameShape(QFrame.HLine)
        lay.addWidget(linha)
        aviso = QLabel("<b>O robô vai CADASTRAR estas renovações no SGCOR</b> (1ª tela, coberturas, repasse, parcelas e "
                       "anexos) e mover cada pasta para _CADASTRADOS. Se aparecer pendência, ele para naquela lotérica e "
                       "segue para a próxima." if "Autom" in modo else
                       "O robô vai preencher a 1ª tela de cada lotérica e esperar você: <b>Continuar</b> grava e termina "
                       "sozinho; <b>Pular</b> não grava.")
        aviso.setWordWrap(True)
        lay.addWidget(aviso)
        bts = QDialogButtonBox()
        ok = bts.addButton("Confirmar", QDialogButtonBox.AcceptRole)
        cancelar = bts.addButton("Cancelar", QDialogButtonBox.RejectRole)
        ok.setAutoDefault(False)
        cancelar.setDefault(True)   # Enter sem querer nunca confirma
        cancelar.setFocus()
        bts.accepted.connect(self.accept)
        bts.rejected.connect(self.reject)
        lay.addWidget(bts)


def main() -> int:
    import multiprocessing
    multiprocessing.freeze_support()   # leitura paralela também funciona no .exe (F4)
    if sys.platform == "win32":
        # ícone próprio na barra de tarefas (senão o Windows agrupa com o ícone do Python)
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("GrupoProtege.AutoCOR")
    app = QApplication.instance() or QApplication(sys.argv)   # a instalação pode ter criado (perguntas)
    app.setOrganizationName(ORG)
    app.setApplicationName(APP)
    app.setWindowIcon(QIcon(str(RECURSOS / "icone.ico")))
    app.setStyleSheet(ESTILO)
    j = Janela()
    j.show()
    return app.exec()
