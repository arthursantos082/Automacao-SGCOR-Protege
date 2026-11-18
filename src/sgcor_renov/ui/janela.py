"""Janela principal: pastas, tabela de lotéricas, detalhe/resolução de pendências e execução com confirmação.

Nada é enviado ao SGCOR sem o consultor marcar as lotéricas, clicar em Executar e confirmar o resumo (Q33).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QSpinBox, QSplitter, QTableView, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..config import carregar
from ..estado import Ajuste, Estado
from ..modelos import Caso
from ..numeros import formatar_cnpj, formatar_dinheiro
from .leitor import Leitor
from .tabela import FORMAS, FiltroCasos, ModeloCasos

ORG, APP = "GrupoProtege", "SGCOR-Renovacoes"


def abrir_no_windows(caminho: Path) -> None:
    if sys.platform == "win32":
        os.startfile(caminho)  # noqa: S606 — abre pasta/PDF local escolhido pelo próprio consultor


class Janela(QMainWindow):
    pedir_leitura = Signal(object, object)   # raízes, ajustes

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Renovações Lotéricas → SGCOR")
        self.resize(1400, 820)
        self.cfg = carregar()
        self.estado = Estado()
        self.settings = QSettings(ORG, APP)
        self.lendo = False
        self.reler_depois = False

        self._montar()
        self._iniciar_leitor()
        self._iniciar_observador()
        QTimer.singleShot(0, self.ler)

    # ------------------------------------------------------------------ montagem

    def _montar(self) -> None:
        central = QWidget()
        raiz = QVBoxLayout(central)

        # pastas + consultor
        topo = QGridLayout()
        docs = Path.home() / "Documents"
        self.ed_porto = self._campo_pasta(topo, 0, "Pasta PORTO", "porto", docs / "FECHADOS PORTO")
        self.ed_tokio = self._campo_pasta(topo, 1, "Pasta TOKIO", "tokio", docs / "FECHADOS TOKIO")
        topo.addWidget(QLabel("Consultor / Produtor"), 0, 3)
        self.ed_consultor = QLineEdit(self.settings.value("consultor", ""))
        self.ed_consultor.setPlaceholderText("nome do produtor no SGCOR")
        self.ed_consultor.editingFinished.connect(lambda: self.settings.setValue("consultor", self.ed_consultor.text()))
        topo.addWidget(self.ed_consultor, 0, 4)
        self.bt_sgcor = QPushButton("Verificar conexão ao SGCOR")
        self.bt_sgcor.setEnabled(False)
        self.bt_sgcor.setToolTip("Disponível na F2 (robô do SGCOR)")
        topo.addWidget(self.bt_sgcor, 1, 4)
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
        for b in (bt_todos, bt_nenhum, bt_ler):
            filtros.addWidget(b)
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
        self.cb_modo.addItem("Conferência — preenche e para antes de salvar", "conferencia")
        self.cb_modo.addItem("Automático — disponível na F3", "automatico")
        self.cb_modo.model().item(1).setEnabled(False)
        rodape.addWidget(self.cb_modo)
        rodape.addStretch(1)
        self.lb_contagem = QLabel()
        self.lb_contagem.setMinimumWidth(140)
        self.lb_contagem.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        rodape.addWidget(self.lb_contagem)
        self.bt_executar = QPushButton("Executar selecionadas")
        self.bt_executar.setMinimumHeight(34)
        self.bt_executar.clicked.connect(self.executar)
        rodape.addWidget(self.bt_executar)
        raiz.addLayout(rodape)

        self.setCentralWidget(central)
        self.progresso = QProgressBar()
        self.progresso.setMaximumWidth(260)
        self.progresso.setVisible(False)
        self.statusBar().addPermanentWidget(self.progresso)

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
            "Vigência": f"{p.vigencia_inicio} a {p.vigencia_fim}" if p and p.vigencia_inicio else "vem do SGCOR",
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
        self.bt_executar.setEnabled(n > 0)

    def executar(self) -> None:
        sel = self.modelo.selecionados()
        if not sel:
            return
        if not self.ed_consultor.text().strip():
            QMessageBox.information(self, "Consultor", "Informe o consultor/produtor antes de executar.")
            return
        dlg = Confirmacao(self, sel, self.cb_modo.currentText(), self.ed_consultor.text().strip())
        if dlg.exec() != QDialog.Accepted:
            self.statusBar().showMessage("Execução cancelada. Nada foi enviado ao SGCOR.", 8000)
            return
        QMessageBox.information(
            self, "Robô do SGCOR",
            "Confirmado.\n\nO robô que preenche o SGCOR entra na F2 — nesta versão nada é enviado ao SGCOR.")

    def closeEvent(self, ev):
        self.thread.quit()
        self.thread.wait(3000)
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
        lay.addWidget(QLabel("O robô vai preencher o SGCOR para estas lotéricas. No modo Conferência ele para antes de "
                             "salvar cada uma."))
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
    app = QApplication(sys.argv)
    app.setOrganizationName(ORG)
    app.setApplicationName(APP)
    j = Janela()
    j.show()
    return app.exec()
