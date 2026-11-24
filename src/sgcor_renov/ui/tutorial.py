"""Tutorial que abre junto com o app, antes de ler as pastas: como organizar as pastas e como usar o robô."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

PASTA = "📁"
PDF = "📄"


def _arvore(raiz: str, loterica: str) -> str:
    return (f"<table cellspacing='0' cellpadding='3' style='font-family: Consolas, monospace; font-size: 13px;'>"
            f"<tr><td colspan='3'>{PASTA} <b>{raiz}</b></td></tr>"
            f"<tr><td width='22'></td><td colspan='2'>{PASTA} <b>{loterica}</b></td></tr>"
            f"<tr><td></td><td width='22'></td><td>{PDF} ACORDO {loterica}.pdf</td></tr>"
            f"<tr><td></td><td></td><td>{PDF} {loterica}.pdf</td></tr>"
            f"</table>")


PAGINAS = [
    ("1. Organize as pastas",
     "Dentro de <b>FECHADOS PORTO</b> e <b>FECHADOS TOKIO</b>, cada lotérica tem a <b>sua própria pasta, com o nome "
     "da lotérica</b>. Dentro dela ficam só 2 PDFs: o <b>acordo</b> (o nome começa com <b>ACORDO</b> seguido do nome da "
     "lotérica) e a <b>proposta</b> da seguradora (com o nome da lotérica)."
     "<br><br>" + _arvore("FECHADOS TOKIO", "COSTA &amp; CANDIDA LTDA") +
     "<br><ul style='margin-left: -20px;'>"
     "<li>Uma pasta por lotérica; nada de PDF solto direto em FECHADOS PORTO/TOKIO.</li>"
     "<li>Lotérica da Porto vai em FECHADOS PORTO; da Tokio, em FECHADOS TOKIO.</li>"
     "<li>Baixe a proposta pelo botão de <b>baixar</b> do portal da seguradora — impressa em PDF ela vira imagem e o "
     "AutoCOR não lê. Acordo em imagem (print, PNG ou JPG) fica em <b>laranja</b>: informe as parcelas e a forma no Resolver.</li>"
     "<li>A pasta <b>_CADASTRADOS</b> é do robô e fica ao lado de FECHADOS PORTO e FECHADOS TOKIO (se não existir, ele "
     "cria): ele move para lá cada lotérica que terminar. Não coloque nada nela.</li>"
     "</ul>"),
    ("2. Confira as lotéricas",
     "O AutoCOR lê as pastas e mostra cada lotérica na lista:"
     "<ul style='margin-left: -20px;'>"
     "<li><span style='color:#2ea043;'><b>Pronto</b></span> — tudo foi entendido (parcelas e forma do acordo, valores "
     "da proposta, bônus do repasse). Pode ser cadastrada.</li>"
     "<li><span style='color:#f0533f;'><b>Pendente</b></span> — falta alguma coisa. Clique na lotérica: o motivo aparece "
     "à direita. Corrija a pasta/PDF ou informe parcelas e forma em <b>Resolver</b> e clique em <b>Aplicar</b>.</li>"
     "</ul>"
     "A lista se atualiza sozinha quando você mexe nas pastas. Nada vai para o SGCOR nesta etapa."),
    ("3. Conecte ao SGCOR",
     "<ol style='margin-left: -20px;'>"
     "<li>Clique em <b>Verificar conexão ao SGCOR</b>. Abre uma janela do Chrome só do robô.</li>"
     "<li>Se pedir login, entre com o <b>seu usuário</b> nessa janela. O AutoCOR conecta sozinho quando o login "
     "termina (o robô nunca digita a sua senha).</li>"
     "<li>Escolha o <b>seu nome</b> em <b>Consultor / Produtor</b>: é o produtor que vai no repasse.</li>"
     "</ol>"),
    ("4. Execute",
     "<ol style='margin-left: -20px;'>"
     "<li>Marque as lotéricas <b>Prontas</b> que quer cadastrar (ou <b>Marcar prontas visíveis</b>).</li>"
     "<li>Clique em <b>Executar selecionadas</b>, confira o resumo e clique em <b>Confirmar</b>.</li>"
     "<li>O robô faz tudo no SGCOR: 1ª tela, coberturas, repasse, parcelas e anexos, e move a pasta para "
     "<b>_CADASTRADOS</b>. Acompanhe pelo log, embaixo.</li>"
     "<li>Se algo der errado depois de criada a renovação, ela fica <b>Pela metade</b>: execute de novo que ele "
     "continua de onde parou, ou termine no SGCOR.</li>"
     "</ol>"
     "Em <b>Ver cadastradas</b> ficam todas as lotéricas já cadastradas, com o ID do SGCOR."),
]


class Tutorial(QDialog):
    def __init__(self, pai, logo: Path, ocultar: bool):
        super().__init__(pai)
        self.setWindowTitle("AutoCOR — como usar")
        self.setMinimumSize(720, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        topo = QFrame()
        topo.setObjectName("cabecalho")
        tl = QHBoxLayout(topo)
        tl.setContentsMargins(20, 14, 20, 14)
        img = QLabel()
        img.setPixmap(QPixmap(str(logo)).scaledToHeight(48, Qt.SmoothTransformation))
        tl.addWidget(img)
        tl.addStretch(1)
        boas = QLabel("Bem-vindo ao <b>AutoCOR</b><br><span style='font-size: 12px;'>renovações lotéricas → SGCOR"
                      "</span>")
        boas.setObjectName("titulo")
        boas.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        tl.addWidget(boas)
        lay.addWidget(topo)

        corpo = QVBoxLayout()
        corpo.setContentsMargins(28, 20, 28, 16)
        self.paginas = QStackedWidget()
        for titulo, html in PAGINAS:
            w = QWidget()
            pl = QVBoxLayout(w)
            pl.setContentsMargins(0, 0, 0, 0)
            t = QLabel(titulo)
            t.setStyleSheet("font-size: 18px; font-weight: 600;")
            pl.addWidget(t)
            texto = QLabel(html)
            texto.setWordWrap(True)
            texto.setTextFormat(Qt.RichText)
            texto.setStyleSheet("font-size: 13px;")
            texto.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            pl.addWidget(texto, 1)
            self.paginas.addWidget(w)
        corpo.addWidget(self.paginas, 1)

        self.pontos = QLabel()
        self.pontos.setAlignment(Qt.AlignCenter)
        self.pontos.setTextFormat(Qt.RichText)
        corpo.addWidget(self.pontos)

        rod = QHBoxLayout()
        self.ck_ocultar = QCheckBox("Não mostrar ao abrir o AutoCOR")
        self.ck_ocultar.setChecked(ocultar)
        rod.addWidget(self.ck_ocultar)
        rod.addStretch(1)
        self.bt_voltar = QPushButton("Voltar")
        self.bt_proximo = QPushButton("Próximo")
        self.bt_proximo.setObjectName("primario")
        self.bt_proximo.setMinimumHeight(32)
        self.bt_proximo.setDefault(True)
        self.bt_voltar.clicked.connect(lambda: self._ir(-1))
        self.bt_proximo.clicked.connect(lambda: self._ir(+1))
        rod.addWidget(self.bt_voltar)
        rod.addWidget(self.bt_proximo)
        corpo.addLayout(rod)
        lay.addLayout(corpo, 1)
        self._ir(0)

    def _ir(self, passo: int) -> None:
        i = self.paginas.currentIndex() + passo
        if i >= self.paginas.count():
            self.accept()
            return
        self.paginas.setCurrentIndex(max(i, 0))
        i = self.paginas.currentIndex()
        ultima = i == self.paginas.count() - 1
        self.bt_voltar.setEnabled(i > 0)
        self.bt_proximo.setText("Começar" if ultima else "Próximo")
        self.pontos.setText("&nbsp;&nbsp;".join(
            f"<span style='font-size: 18px; color: {'#5b8def' if k == i else '#6b7280'};'>●</span>"
            for k in range(self.paginas.count())))
