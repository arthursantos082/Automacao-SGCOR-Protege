"""Lotéricas já cadastradas: as pastas em FECHADOS X/_CADASTRADOS, com o ID do SGCOR quando foi o robô que fez."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from ..estado import Estado
from ..scanner import seguradora_da_pasta


@dataclass
class Cadastrada:
    pasta: Path
    nome: str
    seguradora: str
    proposta_id: str = ""
    produtor: str = ""
    quando: str = ""          # "aaaa-mm-dd hh:mm:ss" (vazio = movida à mão / antes do registro)


def listar(raizes: list[Path], estado: Estado) -> list[Cadastrada]:
    reg = estado.cadastradas()
    out: list[Cadastrada] = []
    for raiz in raizes:
        dir_cad = raiz / "_CADASTRADOS"
        if not dir_cad.is_dir():
            continue
        try:
            seg = seguradora_da_pasta(raiz)
        except ValueError:
            seg = ""
        for p in dir_cad.iterdir():
            if not p.is_dir():
                continue
            r = reg.get(str(p), {})
            out.append(Cadastrada(p, r.get("nome") or p.name, r.get("seguradora") or seg,
                                  r.get("proposta_id") or "", r.get("produtor") or "", r.get("quando") or ""))
    # mais recentes primeiro; as sem registro (movidas à mão) no fim, por nome
    com = sorted((c for c in out if c.quando), key=lambda c: c.quando, reverse=True)
    sem = sorted((c for c in out if not c.quando), key=lambda c: c.nome)
    return com + sem


def _data_br(quando: str) -> str:
    if not quando:
        return "—"
    d, _, h = quando.partition(" ")
    a, m, dia = d.split("-")
    return f"{dia}/{m}/{a} {h[:5]}".strip()


class JanelaCadastradas(QDialog):
    COLUNAS = ["Seguradora", "Lotérica", "ID no SGCOR", "Cadastrada em", "Produtor"]

    def __init__(self, pai, raizes: list[Path], estado: Estado, abrir):
        super().__init__(pai)
        self.setWindowTitle("Lotéricas cadastradas")
        self.resize(1000, 560)
        self.abrir = abrir
        self.itens = listar(raizes, estado)
        lay = QVBoxLayout(self)
        robo = sum(1 for c in self.itens if c.proposta_id)
        lay.addWidget(QLabel(f"<b>{len(self.itens)} lotérica(s)</b> em _CADASTRADOS · {robo} pelo robô · "
                             f"{len(self.itens) - robo} movida(s) à mão (sem ID registrado)"))
        self.ed_busca = QLineEdit()
        self.ed_busca.setPlaceholderText("Buscar lotérica ou ID…")
        self.ed_busca.textChanged.connect(self._filtrar)
        lay.addWidget(self.ed_busca)

        self.t = QTableWidget(len(self.itens), len(self.COLUNAS))
        self.t.setHorizontalHeaderLabels(self.COLUNAS)
        for r, c in enumerate(self.itens):
            vals = [c.seguradora.title(), c.nome, c.proposta_id or "—", _data_br(c.quando), c.produtor or "—"]
            for col, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if col in (2, 3):
                    it.setTextAlignment(Qt.AlignCenter)
                self.t.setItem(r, col, it)
        self.t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.t.setSelectionMode(QAbstractItemView.SingleSelection)
        self.t.verticalHeader().setVisible(False)
        self.t.setAlternatingRowColors(True)
        cab = self.t.horizontalHeader()
        cab.setSectionResizeMode(QHeaderView.ResizeToContents)
        cab.setSectionResizeMode(1, QHeaderView.Stretch)
        self.t.doubleClicked.connect(lambda _: self._abrir_pasta())
        lay.addWidget(self.t, 1)

        bts = QHBoxLayout()
        self.bt_pasta = QPushButton("Abrir pasta")
        self.bt_pasta.clicked.connect(self._abrir_pasta)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.accept)
        bts.addWidget(self.bt_pasta)
        bts.addStretch(1)
        bts.addWidget(fechar)
        lay.addLayout(bts)

    def _filtrar(self, texto: str) -> None:
        t = texto.strip().lower()
        for r, c in enumerate(self.itens):
            self.t.setRowHidden(r, bool(t) and t not in c.nome.lower() and t not in c.proposta_id)

    def _abrir_pasta(self) -> None:
        r = self.t.currentRow()
        if 0 <= r < len(self.itens) and not self.t.isRowHidden(r):
            self.abrir(self.itens[r].pasta)
