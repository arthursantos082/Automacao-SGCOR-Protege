"""Q83: diálogo "Alterar vigência" do Resolver — início e fim da vigência de uma lotérica."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout


class DialogoVigencia(QDialog):
    """Q83: início e fim da vigência desta lotérica. "Usar a padrão" volta à da configuração."""

    def __init__(self, pai, nome: str, ini: str, fim: str, padrao_ini: str, padrao_fim: str, da_proposta: str | None):
        super().__init__(pai)
        self.setWindowTitle("Alterar vigência")
        self.resultado: str | None = None
        lay = QVBoxLayout(self)
        texto = (f"<b>{nome}</b><br>Padrão da configuração: {padrao_ini} a {padrao_fim}"
                 + (f"<br>A proposta começa em {da_proposta}" if da_proposta else ""))
        info = QLabel(texto)
        info.setWordWrap(True)
        lay.addWidget(info)
        form = QFormLayout()
        self.ed_ini, self.ed_fim = QLineEdit(ini), QLineEdit(fim)
        for ed in (self.ed_ini, self.ed_fim):
            ed.setInputMask("99/99/9999")
        form.addRow("Início:", self.ed_ini)
        form.addRow("Fim:", self.ed_fim)
        lay.addLayout(form)
        self.lb_erro = QLabel()
        self.lb_erro.setStyleSheet("color: #f0533f;")
        lay.addWidget(self.lb_erro)
        bts = QDialogButtonBox()
        bts.addButton("Salvar", QDialogButtonBox.AcceptRole).clicked.connect(self._salvar)
        bts.addButton("Usar a padrão", QDialogButtonBox.ResetRole).clicked.connect(self._padrao)
        bts.addButton("Cancelar", QDialogButtonBox.RejectRole).clicked.connect(self.reject)
        lay.addWidget(bts)
        self.padrao = (padrao_ini, padrao_fim)

    @staticmethod
    def _data(t: str):
        try:
            return datetime.strptime(t, "%d/%m/%Y")
        except ValueError:
            return None

    def _salvar(self) -> None:
        ini, fim = self.ed_ini.text(), self.ed_fim.text()
        d_ini, d_fim = self._data(ini), self._data(fim)
        if not d_ini or not d_fim:
            self.lb_erro.setText("Data inválida: use dd/mm/aaaa.")
            return
        if d_fim <= d_ini:
            self.lb_erro.setText("O fim tem que ser depois do início.")
            return
        self.resultado = None if (ini, fim) == self.padrao else f"{ini} a {fim}"
        self.accept()

    def _padrao(self) -> None:
        self.resultado = None
        self.accept()
