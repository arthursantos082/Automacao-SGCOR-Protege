"""Janela principal: pastas, tabela de lotéricas, detalhe/resolução de pendências e execução com confirmação.

Nada é enviado ao SGCOR sem o consultor marcar as lotéricas, clicar em Executar e confirmar o resumo (Q33).
"""
from __future__ import annotations

import os
import re
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QActionGroup, QColor, QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QInputDialog, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QProgressDialog, QPushButton, QScrollArea, QSpinBox, QSplitter,
    QTableView, QToolButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import atualizacao, instalacao
from ..config import carregar
from ..instalacao import VERSAO
from ..estado import Ajuste, Estado
from ..modelos import Caso
from ..numeros import formatar_cnpj, formatar_dinheiro, mais_um_ano
from ..propostas import SEM_APOLICE_ANTERIOR
from ..regras import onde_pendencia, vigencia_do_caso
from ..scanner import PEND_CNPJ_ACORDO, lotericas_cadastradas
from .cadastradas import JanelaCadastradas
from .leitor import Leitor
from .tabela import COL_CNPJ, FORMAS, LARANJA, DelegadoCopiar, FiltroCasos, ModeloCasos, icone_copiar
from .trabalhador import Trabalhador, mover_para_cadastrados
from .tutorial import Tutorial
from .vigencia import DialogoVigencia

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
QPushButton[pendente="true"] {{ background: #f2c230; color: #1f1800; border: 1px solid #c99a00;
                                      border-radius: 4px; padding: 4px 12px; font-weight: 600; }}
QPushButton[pendente="true"]:hover {{ background: #ffd34d; }}
QPushButton[pendente="true"]:disabled {{ background: #b39a4d; color: #3d3100; }}
"""

# tema: "sistema" segue o Windows; "claro"/"escuro" forçam (guardado em QSettings "tema")
TEMAS = {"sistema": ("Automático (igual ao Windows)", Qt.ColorScheme.Unknown),
         "claro": ("Claro", Qt.ColorScheme.Light),
         "escuro": ("Escuro", Qt.ColorScheme.Dark)}


def aplicar_tema(chave: str) -> None:
    QGuiApplication.styleHints().setColorScheme(TEMAS.get(chave, TEMAS["sistema"])[1])


def estilo_com_tema(app: QApplication) -> None:
    """Q89: no Windows 10 o Qt usa o estilo "windowsvista", que ignora o tema (claro/escuro não mudava nada). Lá
    vai o "Fusion", que troca; no Windows 11 o "windows11" já troca e fica como está."""
    if app.style().name().lower() == "windowsvista":
        app.setStyle("Fusion")


def abrir_no_windows(caminho: Path) -> None:
    if sys.platform == "win32":
        os.startfile(caminho)  # noqa: S606 — abre pasta/PDF local escolhido pelo próprio consultor


class Janela(QMainWindow):
    pedir_leitura = Signal(object, object)   # raízes, ajustes
    atualizacao_consultada = Signal(object, object, bool)   # Release | None, erro | None, silencioso
    download_progresso = Signal(int, int)
    download_fim = Signal(object, object)                    # exe novo | None, erro | None

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{NOME} {VERSAO} — renovações lotéricas → SGCOR")
        self.setMinimumSize(900, 560)
        self._tamanho_inicial()
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
        self.atualizacao_consultada.connect(self._atualizacao_consultada, Qt.QueuedConnection)
        self.download_progresso.connect(self._progresso_download, Qt.QueuedConnection)
        self.download_fim.connect(self._download_fim, Qt.QueuedConnection)
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
        bt_tema = QPushButton("Tema")
        bt_tema.setToolTip("Tema claro ou escuro")
        menu_tema = QMenu(bt_tema)
        grupo_tema = QActionGroup(menu_tema)
        tema_atual = str(self.settings.value("tema", "sistema"))
        for chave, (rotulo, _) in TEMAS.items():
            acao = menu_tema.addAction(rotulo)
            acao.setCheckable(True)
            acao.setChecked(chave == tema_atual)
            acao.triggered.connect(lambda _=False, k=chave: self._trocar_tema(k))
            grupo_tema.addAction(acao)
        bt_tema.setMenu(menu_tema)
        cl.addWidget(bt_tema)
        bt_atualizar = QPushButton("Verificar atualização")
        bt_atualizar.setToolTip(f"Você está na versão {VERSAO}. Procura versão nova no GitHub.")
        bt_atualizar.clicked.connect(lambda: self.checar_atualizacao(silencioso=False))
        cl.addWidget(bt_atualizar)
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
        self.bt_sgcor.setObjectName("sgcor")
        self._sgcor_pendente(True)            # amarelo até o consultor logar e a conexão dar certo
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
        for chave, rotulo in (("", "Todas"), ("Pronto", "Prontas"), ("Pendente", "Pendentes"),
                              ("Metade", "Pela metade")):
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
        self.bt_mover = QPushButton("Mover para cadastradas")
        self.bt_mover.setToolTip("Move a lotérica selecionada para _CADASTRADOS (ex.: cadastro terminado à mão no SGCOR)")
        self.bt_mover.clicked.connect(self._mover_para_cadastradas)
        self.bt_mover.setEnabled(False)
        filtros.addSpacing(16)
        filtros.addWidget(self.bt_mover)
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
        self.copiar_cnpj = DelegadoCopiar(self.tabela)        # ícone de copiar ao lado do CNPJ
        self.copiar_cnpj.copiado.connect(self._cnpj_copiado)
        self.tabela.setItemDelegateForColumn(COL_CNPJ, self.copiar_cnpj)
        cab = self.tabela.horizontalHeader()
        cab.setSectionResizeMode(QHeaderView.ResizeToContents)   # nomes inteiros; em tela pequena, rola na horizontal
        cab.setStretchLastSection(True)
        self.tabela.selectionModel().currentRowChanged.connect(lambda cur, _: self._mostrar(cur))

        # tudo redimensionável: tabela | detalhe (horizontal) e, embaixo, o log (vertical)
        self.split_h = QSplitter(Qt.Horizontal)
        self.split_h.setChildrenCollapsible(False)
        self.split_h.addWidget(self.tabela)
        self.split_h.addWidget(self._painel_detalhe())
        self.split_h.setStretchFactor(0, 3)
        self.split_h.setStretchFactor(1, 1)
        self.split_v = QSplitter(Qt.Vertical)
        self.split_v.setChildrenCollapsible(False)
        self.split_v.addWidget(self.split_h)
        raiz.addWidget(self.split_v, 1)

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
        self.log.setMinimumHeight(50)
        self.log.setPlaceholderText("Log do robô")
        self.split_v.addWidget(self.log)
        self.split_v.setStretchFactor(0, 5)
        self.split_v.setStretchFactor(1, 1)
        self._restaurar_divisorias()

        self.setCentralWidget(central)
        self.progresso = QProgressBar()
        self.progresso.setMaximumWidth(260)
        self.progresso.setVisible(False)
        self.statusBar().addPermanentWidget(self.progresso)

    def _inicio(self) -> None:
        """Ao abrir: tutorial primeiro (a menos que o consultor tenha desligado), depois a leitura das pastas."""
        if not self.settings.value("tutorial_ocultar", False, type=bool):
            self.mostrar_tutorial()
        from ..pdftexto import ERRO_CRIPTOGRAFIA
        if ERRO_CRIPTOGRAFIA:   # Q78: os PDFs normais são lidos; só PDF protegido daria erro — mostra a causa
            self.log.appendPlainText(f"Aviso: o componente de criptografia não carregou nesta máquina; PDFs "
                                     f"protegidos não serão lidos (os normais, sim). Detalhe: {ERRO_CRIPTOGRAFIA}")
        self.ler()
        if self._instalado():
            QTimer.singleShot(3000, lambda: self.checar_atualizacao(silencioso=True))

    # ------------------------------------------------------------------ atualização

    @staticmethod
    def _instalado() -> bool:
        return getattr(sys, "frozen", False) and instalacao.instalado_em(Path(sys.executable).parent,
                                                                         instalacao.destino_padrao())

    def checar_atualizacao(self, silencioso: bool) -> None:
        if not self._instalado():
            if not silencioso:
                QMessageBox.information(self, "Atualização", "A atualização automática só funciona no AutoCOR "
                                                             "instalado (C:\\Program Files\\AutoCOR).")
            return

        def consultar():
            try:
                self.atualizacao_consultada.emit(atualizacao.ultima_release(self.cfg.repositorio), None, silencioso)
            except Exception as e:   # noqa: BLE001 — sem internet/GitHub fora: não atrapalha o uso
                self.atualizacao_consultada.emit(None, e, silencioso)
        threading.Thread(target=consultar, daemon=True).start()

    def _atualizacao_consultada(self, release, erro, silencioso: bool) -> None:
        if erro or not atualizacao.tem_nova(VERSAO, release):
            if not silencioso:
                QMessageBox.information(self, "Atualização", f"Não consegui consultar o GitHub: {erro}" if erro
                                        else f"Você já está na versão mais nova ({VERSAO}).")
            return
        if self.executando:
            self.statusBar().showMessage(f"Versão {release.versao} disponível: atualize depois do lote "
                                         f"(Verificar atualização).", 15000)
            return
        tam = f"{release.tamanho / 2**20:.0f} MB" if release.tamanho else ""
        r = QMessageBox.question(self, "Atualização disponível",
                                 f"A versão {release.versao} do {NOME} está disponível (você tem a {VERSAO}).\n\n"
                                 f"{release.notas[:600]}\n\nAtualizar agora? Baixa {tam}, fecha o {NOME} e instala "
                                 f"(o Windows vai pedir permissão de administrador).",
                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if r == QMessageBox.Yes:
            self._baixar(release)

    def _baixar(self, release) -> None:
        self.dlg_download = QProgressDialog(f"Baixando o {NOME} {release.versao}…", "Cancelar", 0, 100, self)
        self.dlg_download.setWindowTitle("Atualização")
        self.dlg_download.setWindowModality(Qt.WindowModal)
        self.dlg_download.setMinimumDuration(0)
        self.dlg_download.setValue(0)
        cancelar = threading.Event()
        self.dlg_download.canceled.connect(cancelar.set)

        def baixar():
            try:
                exe = atualizacao.baixar(release, lambda f, t: self.download_progresso.emit(f, t), cancelar.is_set)
                self.download_fim.emit(exe, None)
            except Exception as e:   # noqa: BLE001
                self.download_fim.emit(None, e)
        threading.Thread(target=baixar, daemon=True).start()

    def _progresso_download(self, feito: int, total: int) -> None:
        if total:
            self.dlg_download.setValue(min(99, feito * 100 // total))

    def _download_fim(self, exe, erro) -> None:
        self.dlg_download.reset()
        if erro:
            QMessageBox.warning(self, "Atualização", f"Não consegui baixar a atualização:\n{erro}")
            return
        if exe is None:
            return   # cancelado
        if not instalacao.abrir_instalador(exe):
            QMessageBox.warning(self, "Atualização", "A atualização precisa de permissão de administrador.")
            return
        self.close()   # libera os arquivos; o instalador novo espera este fechar e substitui

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

    def _tamanho_inicial(self) -> None:
        """Ocupa ~90% da tela disponível (qualquer resolução); em tela pequena, abre maximizada."""
        tela = QGuiApplication.primaryScreen()
        if tela is None:
            self.resize(1400, 820)
            return
        g = tela.availableGeometry()
        self.resize(int(g.width() * 0.9), int(g.height() * 0.9))
        self.move(g.x() + (g.width() - self.width()) // 2, g.y() + (g.height() - self.height()) // 2)
        if g.width() < 1366 or g.height() < 768:
            self.setWindowState(Qt.WindowMaximized)

    def _divisorias(self) -> list[QSplitter]:
        return [self.split_h, self.split_v, self.split_det]

    def _restaurar_divisorias(self) -> None:
        for i, s in enumerate(self._divisorias()):
            estado = self.settings.value(f"divisoria_{i}")
            if estado is not None:
                s.restoreState(estado)

    def _guardar_divisorias(self) -> None:
        for i, s in enumerate(self._divisorias()):
            self.settings.setValue(f"divisoria_{i}", s.saveState())

    @staticmethod
    def _secao(titulo: str, conteudo: QWidget, embaixo: QWidget | None = None) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(QLabel(titulo))
        lay.addWidget(conteudo, 1)
        if embaixo is not None:
            lay.addWidget(embaixo)
        return w

    def _painel_detalhe(self) -> QWidget:
        """Painel da direita: rola quando não cabe, e as listas são redimensionáveis (arrastar as divisórias)."""
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QFrame.NoFrame)
        rolagem.setMinimumWidth(320)
        w = QWidget()
        rolagem.setWidget(w)
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
            lb.setWordWrap(True)
            lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.info[k] = lb
            if k == "CNPJ":
                linha = QHBoxLayout()
                linha.setContentsMargins(0, 0, 0, 0)
                linha.addWidget(lb)
                self.bt_copiar_cnpj = QToolButton()
                self.bt_copiar_cnpj.setIcon(icone_copiar())
                self.bt_copiar_cnpj.setAutoRaise(True)
                self.bt_copiar_cnpj.setToolTip("Copiar CNPJ")
                self.bt_copiar_cnpj.setCursor(Qt.PointingHandCursor)
                self.bt_copiar_cnpj.clicked.connect(self._copiar_cnpj_detalhe)
                linha.addWidget(self.bt_copiar_cnpj)
                linha.addStretch(1)
                self.form_info.addRow(k + ":", linha)
            else:
                self.form_info.addRow(k + ":", lb)
        lay.addLayout(self.form_info)

        self.lb_combinado = QLabel()
        self.lb_combinado.setWordWrap(True)
        self.lb_combinado.setStyleSheet("color: #8b949e; font-style: italic;")   # legível nos dois temas
        lay.addWidget(self.lb_combinado)

        self.ls_pend = QListWidget()
        self.ls_avisos = QListWidget()
        self.ls_cob = QListWidget()
        for ls in (self.ls_pend, self.ls_avisos, self.ls_cob):
            ls.setWordWrap(True)
            ls.setMinimumHeight(48)
            ls.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            ls.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)

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
        self.bt_alterar_vig = QPushButton("Alterar vigência…")
        self.bt_alterar_vig.setToolTip("Cadastrar esta lotérica com outra vigência (no lugar da padrão da configuração)")
        self.bt_alterar_vig.clicked.connect(self._alterar_vigencia)
        f.addRow(self.bt_alterar_vig)
        # Q64: vigência da proposta diferente da padrão não tem como corrigir no PDF → o consultor confirma a padrão
        self.bt_vigencia = QPushButton("Seguir com a vigência padrão…")
        self.bt_vigencia.setToolTip("A vigência vem da proposta e não dá para corrigir no PDF: confirme para "
                                    "cadastrar com a vigência padrão da configuração")
        self.bt_vigencia.clicked.connect(self._confirmar_vigencia)
        self.bt_vigencia.setVisible(False)
        self._amarelo(self.bt_vigencia, True)         # só aparece quando há a pendência: pede atenção
        # Q68: nº da apólice anterior que não veio na proposta (ex.: "Renova Apólice nº 1234") → o consultor confirma
        self.bt_apolice = QPushButton("Seguir sem o nº da apólice anterior…")
        self.bt_apolice.setToolTip("O robô acha a apólice anterior no SGCOR pelo CNPJ e pela vigência, sem usar "
                                   "esse número: confirme para seguir")
        self.bt_apolice.clicked.connect(self._confirmar_sem_apolice)
        self.bt_apolice.setVisible(False)
        self._amarelo(self.bt_apolice, True)
        self.botoes_pend = QWidget()                  # botões de confirmar, logo abaixo da lista de Pendências
        bl_pend = QVBoxLayout(self.botoes_pend)
        bl_pend.setContentsMargins(0, 2, 0, 0)
        bl_pend.setSpacing(4)
        # Q80: o acordo cita outro CNPJ (cliente com mais de uma lotérica) → o consultor confirma a lotérica
        self.bt_loterica = QPushButton("Confirmar a lotérica…")
        self.bt_loterica.setToolTip("O acordo cita outro CNPJ (o cliente pode ter mais de uma lotérica): confirme que "
                                    "este acordo vale para esta lotérica")
        self.bt_loterica.clicked.connect(self._confirmar_loterica)
        self.bt_loterica.setVisible(False)
        self._amarelo(self.bt_loterica, True)
        bl_pend.addWidget(self.bt_vigencia)
        bl_pend.addWidget(self.bt_apolice)
        bl_pend.addWidget(self.bt_loterica)

        self.split_det = QSplitter(Qt.Vertical)
        self.split_det.setChildrenCollapsible(False)
        self.split_det.setHandleWidth(8)
        for titulo, conteudo, embaixo in (
                ("Pendências", self.ls_pend, self.botoes_pend), ("Avisos", self.ls_avisos, None),   # Q64
                ("Coberturas da proposta (LMI) — ✎ = o robô ajusta no SGCOR", self.ls_cob, None)):
            self.split_det.addWidget(self._secao(titulo, conteudo, embaixo))
        self.split_det.addWidget(box)
        for i, peso in enumerate((1, 1, 2, 0)):
            self.split_det.setStretchFactor(i, peso)
        self.split_det.setMinimumHeight(420)
        lay.addWidget(self.split_det, 1)

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
        self._atual: Caso | None = None
        self._habilitar_detalhe(False)
        return rolagem

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
        metade = {c.pasta: m[0] for c in casos if (m := self.estado.pela_metade(c.pasta))}
        self.modelo.definir(casos, metade)
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
                    self.bt_pasta, self.bt_acordo, self.bt_prop, self.bt_alterar_vig):
            wdg.setEnabled(sim)
        self.bt_mover.setEnabled(sim and not self.executando)

    def _mostrar(self, idx) -> None:
        c: Caso | None = idx.data(Qt.UserRole) if idx.isValid() else None
        self._atual = c
        self._habilitar_detalhe(c is not None)
        onde = set().union(*(onde_pendencia(t) for t in c.pendencias)) if c else set()
        for botao, pdf, no in ((self.bt_acordo, "acordo", "no acordo"), (self.bt_prop, "proposta", "na proposta")):  # Q63
            self._amarelo(botao, pdf in onde)
            botao.setToolTip(f"Há pendência {no}: abra para conferir" if pdf in onde else "")
        if c is None:
            return
        p = c.proposta
        self.lb_titulo.setText(f"{c.nome}  ·  {self.modelo.rotulo_status(c)}")
        vals = {
            "Seguradora": c.seguradora.title(),
            "CNPJ": formatar_cnpj(p.cnpj) if p else "",
            "Apólice anterior": (p.apolice_anterior or "") if p else "",
            "Proposta nº": (p.numero or "") if p else "",
            "Vigência": "{} a {}".format(*vigencia_do_caso(c, self.cfg))
                        + (" (alterada)" if c.vigencia_alterada else " (configuração)"),
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
        self._listar_pendencias(c)
        self.ls_avisos.clear()
        self.ls_avisos.addItems(c.avisos)
        self.ls_cob.clear()
        for cob, chave in c.coberturas:   # Q59: só Incêndio e Valores são ajustados; o resto fica como no SGCOR
            ajusta = chave in self.cfg.coberturas_ajustar
            it = QListWidgetItem(f"{'✎' if ajusta else '  '} R$ {formatar_dinheiro(cob.lmi):>12}   {cob.nome}")
            if not ajusta:
                it.setForeground(QColor("#8b949e"))
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
        for wdg in (self.sp_parcelas, self.cb_forma, self.bt_aplicar, self.bt_desfazer, self.bt_alterar_vig):
            wdg.setEnabled(resolvivel)
        self.bt_mover.setEnabled(resolvivel and not self.executando)
        self.bt_acordo.setEnabled(c.acordo is not None)
        self.bt_prop.setEnabled(bool(c.propostas))
        self.bt_vigencia.setVisible(resolvivel and any(t.startswith("Vigência da proposta") for t in c.pendencias))
        self.bt_apolice.setVisible(resolvivel and any(t.startswith(f"Proposta: {SEM_APOLICE_ANTERIOR}")
                                                      for t in c.pendencias))
        self.bt_loterica.setVisible(resolvivel and bool(c.proposta and c.proposta.cnpj)
                                    and any(t.startswith(PEND_CNPJ_ACORDO) for t in c.pendencias))

    def _abrir_proposta(self) -> None:
        c = self._atual
        alvo = c.proposta_escolhida or (c.propostas[0] if c.propostas else None)
        if alvo:
            abrir_no_windows(alvo)

    def _aplicar_ajuste(self) -> None:
        anterior = self.estado.ajuste(self._atual.pasta) if self._atual and self._atual.pasta.is_dir() else None
        self._salvar_ajuste(Ajuste(
            parcelas=self.sp_parcelas.value() or None,
            forma=self.cb_forma.currentData(),
            proposta=self.cb_proposta.currentData(),
            vigencia=anterior.vigencia if anterior else None,     # não perde as confirmações já feitas
            sem_apolice=anterior.sem_apolice if anterior else False,
            cnpj_confirmado=anterior.cnpj_confirmado if anterior else None,
            vigencia_alterada=anterior.vigencia_alterada if anterior else None,
        ))

    def _alterar_vigencia(self) -> None:
        """Q83: o consultor escolhe a vigência desta lotérica (o robô usa na 1ª tela, na busca da apólice anterior —
        a que termina no início novo — e no aviso de datas do Avançar)."""
        c = self._atual
        if not c or not c.pasta.is_dir():
            return
        p = c.proposta
        if c.vigencia_alterada:
            ini, fim = c.vigencia_alterada
        elif p and p.vigencia_inicio and p.vigencia_inicio != self.cfg.vigencia_inicio:
            ini, fim = p.vigencia_inicio, p.vigencia_fim or mais_um_ano(p.vigencia_inicio)   # sugere a da proposta
        else:
            ini, fim = self.cfg.vigencia_inicio, self.cfg.vigencia_fim
        dlg = DialogoVigencia(self, c.nome, ini, fim, self.cfg.vigencia_inicio, self.cfg.vigencia_fim,
                              p.vigencia_inicio if p else None)
        if dlg.exec() != QDialog.Accepted:
            return
        a = self.estado.ajuste(c.pasta) or Ajuste()
        a.vigencia_alterada = dlg.resultado      # None = voltar à padrão
        self._salvar_ajuste(a)

    def _mover_para_cadastradas(self) -> None:
        """Q84: move a lotérica selecionada para _CADASTRADOS (cadastro feito/terminado à mão no SGCOR)."""
        c = self._atual
        if self.executando:
            QMessageBox.information(self, "Mover para cadastradas", "Espere o lote terminar.")
            return
        if not c or not c.pasta.is_dir():
            return
        metade = self.estado.pela_metade(c.pasta)
        pid, ok = QInputDialog.getText(
            self, "Mover para cadastradas",
            f"Mover “{c.nome}” para _CADASTRADOS?\n\nUse quando o cadastro foi feito ou terminado à mão no SGCOR: a "
            f"pasta sai da lista e não será cadastrada de novo.\n\nID da renovação no SGCOR (opcional):",
            text=metade[0] if metade else "")
        if not ok:
            return
        try:
            destino = mover_para_cadastrados(c.pasta)
        except OSError as e:
            QMessageBox.warning(self, "Mover para cadastradas", f"Não consegui mover a pasta: {e}")
            return
        self.estado.limpar_pela_metade(c.pasta)
        self.estado.registrar_cadastrada(destino, c.nome, c.seguradora, pid.strip(), "movida à mão no AutoCOR")
        self.log.appendPlainText(f"{c.nome}: movida para _CADASTRADOS à mão"
                                 + (f" (ID {pid.strip()})" if pid.strip() else "") + ".")
        self.statusBar().showMessage(f"{c.nome} movida para _CADASTRADOS.", 8000)
        self._atual = None
        self.ler()

    def _confirmar_loterica(self) -> None:
        c = self._atual
        if not c or not c.proposta or not c.proposta.cnpj or not c.pasta.is_dir():
            return
        pend = next((t for t in c.pendencias if t.startswith(PEND_CNPJ_ACORDO)), "")
        citados = pend[pend.find("(") + 1:pend.find(" × ")] if "(" in pend else "outro CNPJ"
        r = QMessageBox.question(
            self, "Confirmar a lotérica",
            f"O acordo cita {citados}, mas a proposta é de {c.proposta.razao_social or c.nome} "
            f"(CNPJ {formatar_cnpj(c.proposta.cnpj)}).\n\n"
            "Isso acontece quando o cliente tem mais de uma lotérica.\n\n"
            "Confirmar que este acordo vale para esta lotérica?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        a = self.estado.ajuste(c.pasta) or Ajuste()
        a.cnpj_confirmado = c.proposta.cnpj
        self._salvar_ajuste(a)

    def _confirmar_sem_apolice(self) -> None:
        c = self._atual
        if not c or not c.pasta.is_dir():
            return
        r = QMessageBox.question(
            self, "Apólice anterior",
            f"Não encontrei o nº da apólice anterior na proposta de {c.nome}.\n\n"
            "O robô não usa esse número: ele acha a apólice anterior no SGCOR pelo CNPJ, pela seguradora e pela "
            "vigência.\n\nSeguir mesmo assim?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        a = self.estado.ajuste(c.pasta) or Ajuste()
        a.sem_apolice = True
        self._salvar_ajuste(a)

    def _confirmar_vigencia(self) -> None:
        c = self._atual
        if not c or not c.proposta or not c.proposta.vigencia_inicio or not c.pasta.is_dir():
            return
        r = QMessageBox.question(
            self, "Vigência",
            f"A proposta de {c.nome} começa em {c.proposta.vigencia_inicio}, mas o AutoCOR vai cadastrar no SGCOR "
            f"com a vigência padrão: {self.cfg.vigencia_inicio} a {self.cfg.vigencia_fim}.\n\n"
            "Seguir com essa vigência mesmo assim?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        a = self.estado.ajuste(c.pasta) or Ajuste()
        a.vigencia = c.proposta.vigencia_inicio
        self._salvar_ajuste(a)

    def _salvar_ajuste(self, a: Ajuste) -> None:
        if not self._atual or not self._atual.pasta.is_dir():
            return
        self.estado.salvar(self._atual.pasta, a)
        self.ler()

    # ------------------------------------------------------------------ execução

    def _atualizar_rodape(self) -> None:
        casos = self.modelo.casos
        cat = [self.modelo.categoria(c) for c in casos]
        self.bt_filtros[""].setText(f"Todas ({len(casos)})")
        self.bt_filtros["Pronto"].setText(f"Prontas ({cat.count('Pronto')})")
        self.bt_filtros["Pendente"].setText(f"Pendentes ({cat.count('Pendente')})")
        self.bt_filtros["Metade"].setText(f"Pela metade ({cat.count('Metade')})")
        n = len(self.modelo.selecionados())
        self.lb_contagem.setText(f"{n} selecionada(s)")
        self.bt_executar.setEnabled(n > 0 and not self.executando)
        cad = len(lotericas_cadastradas([r for r in self._raizes() if r.is_dir()]))
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

    @staticmethod
    def _amarelo(botao: QPushButton, sim: bool) -> None:
        """Botão em amarelo (pede atenção) ou na cor padrão."""
        if botao.property("pendente") == sim:
            return
        botao.setProperty("pendente", sim)
        botao.style().unpolish(botao)
        botao.style().polish(botao)

    def _sgcor_pendente(self, sim: bool) -> None:
        """Botão do SGCOR em amarelo enquanto falta conectar/logar; conectado, volta à cor padrão."""
        self._amarelo(self.bt_sgcor, sim)

    def _trocar_tema(self, chave: str) -> None:
        self.settings.setValue("tema", chave)
        aplicar_tema(chave)
        # com o app aberto, só o fundo trocava: recria o estilo para todas as telas pegarem as cores novas
        app = QApplication.instance()
        app.setStyle(app.style().name())
        app.setStyleSheet(ESTILO)

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
        self._sgcor_pendente(not ok)
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
        if acao == "retomar":
            self._sgcor_pendente(False)   # se o SGCOR ainda pedir login, volta a ficar amarelo
        self.barra_conf.setVisible(False)
        self.trab.decidir(acao)

    def _pausar(self) -> None:
        self.trab.pausa.set()
        self.bt_pausar.setEnabled(False)
        self.statusBar().showMessage("Pausa pedida: o robô para ao terminar a lotérica atual.", 8000)

    def _cnpj_copiado(self, cnpj: str) -> None:
        self.statusBar().showMessage(f"CNPJ {cnpj} copiado.", 4000)

    def _copiar_cnpj_detalhe(self) -> None:
        cnpj = self.info["CNPJ"].text()
        if cnpj and cnpj != "—":
            QGuiApplication.clipboard().setText(cnpj)
            self._cnpj_copiado(cnpj)

    ETAPAS = {"coberturas": "Coberturas", "repasse": "Repasse", "parcelas": "Parcelas", "anexos": "Anexos"}

    def _listar_pendencias(self, c: Caso) -> None:
        """Pendências da pasta e, se a renovação ficou pela metade no SGCOR, onde e por que parou (Q76)."""
        self.ls_pend.clear()
        metade = self.estado.pela_metade_detalhe(c.pasta) if c.pasta.is_dir() else None
        if metade:
            pid, etapa, motivo = metade
            it = QListWidgetItem(f"◐ Pela metade no SGCOR (ID {pid}) — parou na etapa {self.ETAPAS.get(etapa, etapa)}"
                                 + (f": {motivo}" if motivo else "")
                                 + ". Corrija no SGCOR e execute de novo (o robô continua desta etapa) ou termine à mão.")
            it.setForeground(QColor(LARANJA))
            self.ls_pend.addItem(it)
        for t in c.pendencias:
            it = QListWidgetItem("⚠ " + t)
            it.setForeground(QColor("#f0533f"))
            self.ls_pend.addItem(it)

    def _situacao(self, pasta: Path, texto: str) -> None:
        m = re.match(r"Pela metade \(ID (\d+)", texto)
        self.modelo.definir_situacao(pasta, texto, m.group(1) if m else None)
        if m or texto.startswith("Cadastrada"):   # mudou de categoria: contadores e filtro
            self._atualizar_rodape()
            self.filtro.definir()
        if self._atual and self._atual.pasta == pasta:
            self.lb_titulo.setText(f"{self._atual.nome}  ·  {texto}")
            if m or texto.startswith("Cadastrada"):
                self._listar_pendencias(self._atual)

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
        self._sgcor_pendente(True)
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
        self._guardar_divisorias()
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


def identidade_na_barra() -> str | None:
    """Rodando pelo Python (código-fonte): identidade própria, senão o Windows agrupa com o ícone do Python.
    Q93: no AutoCOR.exe, nenhuma — a identidade é a do próprio .exe, a mesma dos atalhos do Menu Iniciar e da área de
    trabalho. Com a própria, o Windows via a janela e o atalho como programas diferentes e o ícone fixado na barra de
    tarefas não ficava."""
    if sys.platform != "win32" or getattr(sys, "frozen", False):
        return None
    return "GrupoProtege.AutoCOR"


def main() -> int:
    import multiprocessing
    multiprocessing.freeze_support()   # leitura paralela também funciona no .exe (F4)
    if (aumid := identidade_na_barra()):
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(aumid)
    app = QApplication.instance() or QApplication(sys.argv)   # a instalação pode ter criado (perguntas)
    app.setOrganizationName(ORG)
    app.setApplicationName(APP)
    app.setWindowIcon(QIcon(str(RECURSOS / "icone.ico")))
    estilo_com_tema(app)
    app.setStyleSheet(ESTILO)
    aplicar_tema(str(QSettings().value("tema", "sistema")))
    j = Janela()
    j.show()
    return app.exec()
