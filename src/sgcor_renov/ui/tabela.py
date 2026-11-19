"""Modelo da tabela de lotéricas."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QEvent, QModelIndex, QRect, QRectF, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from ..modelos import Caso
from ..numeros import formatar_cnpj, formatar_dinheiro

FORMAS = {"boleto": "Boleto", "cartao": "Cartão de crédito", "cartao_porto": "Cartão Porto",
          "debito": "Débito em conta", "pix": "PIX"}
FORMAS_CURTAS = {"boleto": "Boleto", "cartao": "Cartão", "cartao_porto": "Cartão Porto", "debito": "Débito",
                 "pix": "PIX"}

COLUNAS = ["", "Status", "Seguradora", "Lotérica", "CNPJ", "Apólice anterior", "Parcelas", "Forma",
           "Prêmio total", "Comissão → Bônus"]
COL_CNPJ = 4

VERDE, LARANJA, VERMELHO = "#2ea043", "#e8790c", "#f0533f"    # legíveis em claro e escuro


def icone_copiar(cor: str = "#8b949e") -> QIcon:
    """Ícone padrão de copiar (duas folhas sobrepostas), desenhado aqui para não depender do tema do Windows."""
    icone = QIcon()
    for lado in (16, 32, 48):
        pm = QPixmap(lado, lado)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(lado / 16, lado / 16)
        p.setPen(QPen(QColor(cor), 1.4))
        frente = QRectF(5.5, 4.5, 8.5, 10)
        tras = QPainterPath()
        tras.addRoundedRect(QRectF(2, 1.5, 8.5, 10), 1.5, 1.5)
        corte = QPainterPath()
        corte.addRect(frente.adjusted(-1.2, -1.2, 1.2, 1.2))
        p.drawPath(tras.subtracted(corte))      # a folha de trás aparece só fora da da frente
        p.drawRoundedRect(frente, 1.5, 1.5)
        p.end()
        icone.addPixmap(pm)
    return icone


class DelegadoCopiar(QStyledItemDelegate):
    """Célula com o texto e, à direita, o ícone de copiar (sem texto). Clicar no ícone copia o texto da célula."""
    copiado = Signal(str)
    LADO, MARGEM = 16, 6

    def __init__(self, pai=None):
        super().__init__(pai)
        self.icone = icone_copiar()

    def _rect_icone(self, r: QRect) -> QRect:
        return QRect(r.right() - self.LADO - self.MARGEM + 2, r.center().y() - self.LADO // 2 + 1,
                     self.LADO, self.LADO)

    def paint(self, p, opt, idx):
        o = QStyleOptionViewItem(opt)
        self.initStyleOption(o, idx)
        texto, o.text = o.text, ""
        estilo = o.widget.style() if o.widget else QGuiApplication.instance().style()
        estilo.drawControl(QStyle.CE_ItemViewItem, o, p, o.widget)       # fundo, seleção e foco
        if not texto:
            return
        selecionada = bool(opt.state & QStyle.State_Selected)
        p.save()
        p.setPen(opt.palette.color(QPalette.HighlightedText if selecionada else QPalette.Text))
        rt = opt.rect.adjusted(4, 0, -(self.LADO + self.MARGEM + 2), 0)
        p.drawText(rt, Qt.AlignVCenter | Qt.AlignLeft, opt.fontMetrics.elidedText(texto, Qt.ElideRight, rt.width()))
        p.setOpacity(1.0 if opt.state & QStyle.State_MouseOver else 0.75)
        self.icone.paint(p, self._rect_icone(opt.rect))
        p.restore()

    def sizeHint(self, opt, idx):
        s = super().sizeHint(opt, idx)
        s.setWidth(s.width() + self.LADO + self.MARGEM)
        return s

    def editorEvent(self, ev, modelo, opt, idx):
        if ev.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick) \
                and ev.button() == Qt.LeftButton and idx.data() \
                and self._rect_icone(opt.rect).adjusted(-3, -3, 3, 3).contains(ev.position().toPoint()):
            if ev.type() == QEvent.MouseButtonRelease:
                QGuiApplication.clipboard().setText(idx.data())
                self.copiado.emit(idx.data())
            return True                    # o clique no ícone só copia (não seleciona nem abre nada)
        return super().editorEvent(ev, modelo, opt, idx)


class ModeloCasos(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self.casos: list[Caso] = []
        self.marcados: set[Path] = set()
        self.situacao: dict[Path, str] = {}   # o que o robô fez/está fazendo nesta lotérica (sessão atual)
        self.metade: dict[Path, str] = {}     # renovações pela metade no SGCOR: pasta → ID da renovação

    def definir_situacao(self, pasta: Path, texto: str, metade_id: str | None = None) -> None:
        self.situacao[pasta] = texto
        if metade_id:
            self.metade[pasta] = metade_id
        elif texto.startswith("Cadastrada"):
            self.metade.pop(pasta, None)
        for r, c in enumerate(self.casos):
            if c.pasta == pasta:
                self.dataChanged.emit(self.index(r, 1), self.index(r, 1))
                return

    def rotulo_status(self, c: Caso) -> str:
        if c.pasta in self.metade:
            return f"Pela metade (ID {self.metade[c.pasta]})"
        return c.status if c.status == "Pronto" else f"Pendente ({len(c.pendencias)})"

    def cor_status(self, c: Caso) -> str:
        if c.pasta in self.metade:
            return LARANJA            # não confundir com o verde do Pronto
        return VERDE if c.status == "Pronto" else VERMELHO

    def definir(self, casos: list[Caso], metade: dict[Path, str] | None = None) -> None:
        self.beginResetModel()
        self.casos = casos
        if metade is not None:
            self.metade = metade
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
            return QBrush(QColor(self.cor_status(c)))
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
        if role == Qt.ToolTipRole and col == COL_CNPJ:
            return "Clique no ícone para copiar o CNPJ"
        if role == Qt.TextAlignmentRole and col in (6, 8):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role != Qt.DisplayRole:
            return None
        p = c.proposta
        match col:
            case 1:
                base = self.rotulo_status(c)
                robo = self.situacao.get(c.pasta)
                if not robo or robo.startswith("Pela metade"):      # o motivo fica na dica (tooltip)
                    return base
                return f"{base} · {robo[:40]}"
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
