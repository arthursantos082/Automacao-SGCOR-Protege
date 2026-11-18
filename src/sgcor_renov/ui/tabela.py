"""Modelo da tabela de lotéricas."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QBrush, QColor

from ..modelos import Caso
from ..numeros import formatar_cnpj, formatar_dinheiro

FORMAS = {"boleto": "Boleto", "cartao": "Cartão de crédito", "cartao_porto": "Cartão Porto",
          "debito": "Débito em conta", "pix": "PIX"}
FORMAS_CURTAS = {"boleto": "Boleto", "cartao": "Cartão", "cartao_porto": "Cartão Porto", "debito": "Débito",
                 "pix": "PIX"}

COLUNAS = ["", "Status", "Seguradora", "Lotérica", "CNPJ", "Apólice anterior", "Parcelas", "Forma",
           "Prêmio total", "Comissão → Bônus"]


class ModeloCasos(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self.casos: list[Caso] = []
        self.marcados: set[Path] = set()
        self.situacao: dict[Path, str] = {}   # o que o robô fez/está fazendo nesta lotérica (sessão atual)

    def definir_situacao(self, pasta: Path, texto: str) -> None:
        self.situacao[pasta] = texto
        for r, c in enumerate(self.casos):
            if c.pasta == pasta:
                self.dataChanged.emit(self.index(r, 1), self.index(r, 1))
                return

    def definir(self, casos: list[Caso]) -> None:
        self.beginResetModel()
        self.casos = casos
        prontos = {c.pasta for c in casos if c.status == "Pronto"}
        self.marcados &= prontos            # pendente nunca fica marcado
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.casos)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUNAS)

    def headerData(self, sec, orient, role=Qt.DisplayRole):
        if orient == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUNAS[sec]
        return None

    def flags(self, idx):
        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if idx.column() == 0 and self.casos[idx.row()].status == "Pronto":
            f |= Qt.ItemIsUserCheckable
        return f

    def data(self, idx, role=Qt.DisplayRole):
        c = self.casos[idx.row()]
        col = idx.column()
        if role == Qt.CheckStateRole and col == 0:
            if c.status != "Pronto":
                return None
            return Qt.Checked if c.pasta in self.marcados else Qt.Unchecked
        if role == Qt.UserRole:
            return c
        if role == Qt.ForegroundRole and col == 1:
            return QBrush(QColor("#2ea043") if c.status == "Pronto" else QColor("#f0533f"))  # legível em claro e escuro
        if role == Qt.FontRole and col == 1:
            from PySide6.QtGui import QFont
            f = QFont()
            f.setBold(True)
            return f
        if role == Qt.ToolTipRole and col == 1:
            dicas = list(c.pendencias)
            if c.pasta in self.situacao:
                dicas.append("Robô: " + self.situacao[c.pasta])
            return "\n".join(dicas) or None
        if role == Qt.TextAlignmentRole and col in (6, 8):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role != Qt.DisplayRole:
            return None
        p = c.proposta
        match col:
            case 1:
                base = c.status if c.status == "Pronto" else f"Pendente ({len(c.pendencias)})"
                robo = self.situacao.get(c.pasta)
                return f"{base} · {robo[:40]}" if robo else base
            case 2:
                return c.seguradora.title()
            case 3:
                return c.nome
            case 4:
                return formatar_cnpj(p.cnpj) if p else ""
            case 5:
                return (p.apolice_anterior or "") if p else ""
            case 6:
                return f"{c.parcelas}x" if c.parcelas else ""
            case 7:
                return FORMAS_CURTAS.get(c.forma or "", c.forma or "")
            case 8:
                return formatar_dinheiro(c.premio_total)
            case 9:
                if p and p.comissao is not None:
                    return f"{p.comissao}% → R$ {formatar_dinheiro(c.bonus)}" if c.bonus else f"{p.comissao}%"
                return ""
        return ""

    def setData(self, idx, valor, role=Qt.EditRole):
        if role == Qt.CheckStateRole and idx.column() == 0:
            c = self.casos[idx.row()]
            if Qt.CheckState(valor) == Qt.Checked:
                self.marcados.add(c.pasta)
            else:
                self.marcados.discard(c.pasta)
            self.dataChanged.emit(idx, idx, [Qt.CheckStateRole])
            return True
        return False

    def marcar_todos(self, visiveis: list[Caso], marcar: bool) -> None:
        for c in visiveis:
            if c.status == "Pronto":
                (self.marcados.add if marcar else self.marcados.discard)(c.pasta)
        self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, 0), [Qt.CheckStateRole])

    def selecionados(self) -> list[Caso]:
        return [c for c in self.casos if c.pasta in self.marcados and c.status == "Pronto"]


class FiltroCasos(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.status = ""      # "" | "Pronto" | "Pendente"
        self.texto = ""

    def definir(self, status: str | None = None, texto: str | None = None) -> None:
        if status is not None:
            self.status = status
        if texto is not None:
            self.texto = texto.strip().upper()
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        c: Caso = self.sourceModel().casos[row]
        if self.status and c.status != self.status:
            return False
        if self.texto:
            p = c.proposta
            alvo = " ".join([c.nome, (p.cnpj or "") if p else "", (p.apolice_anterior or "") if p else ""]).upper()
            return self.texto in alvo
        return True
