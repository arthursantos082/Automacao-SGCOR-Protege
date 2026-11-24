from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from sgcor_renov.modelos import Caso
from sgcor_renov.ui.tabela import LARANJA, VERDE, VERMELHO, ModeloCasos, icone_copiar

APP = QApplication.instance() or QApplication([])


def _caso(nome, pend=()):
    c = Caso(seguradora="TOKIO", pasta=Path("C:/x") / nome, nome=nome)
    c.pendencias.extend(pend)
    return c


def test_pela_metade_fica_laranja_e_some_ao_cadastrar():
    pronta, metade, pendente = _caso("A"), _caso("B"), _caso("C", ["sem acordo"])
    m = ModeloCasos()
    m.definir([pronta, metade, pendente], {metade.pasta: "66757"})
    assert (m.rotulo_status(pronta), m.cor_status(pronta)) == ("Pronto", VERDE)
    assert (m.rotulo_status(metade), m.cor_status(metade)) == ("Pela metade (ID 66757)", LARANJA)
    assert (m.rotulo_status(pendente), m.cor_status(pendente)) == ("Pendente (1)", VERMELHO)
    assert m.index(1, 1).data(Qt.ForegroundRole).color().name() == LARANJA
    # durante o lote: o robô deixa uma pela metade e termina outra
    m.definir_situacao(pronta.pasta, "Pela metade (ID 1, coberturas): x", "1")
    assert m.cor_status(pronta) == LARANJA
    m.definir_situacao(metade.pasta, "Cadastrada no SGCOR (ID 66757)")
    assert m.cor_status(metade) == VERDE


def test_icone_copiar_desenhado():
    assert not icone_copiar().isNull()


def test_filtro_pela_metade():
    from sgcor_renov.ui.tabela import FiltroCasos
    pronta, metade, pendente = _caso("A"), _caso("B"), _caso("C", ["x"])
    m = ModeloCasos()
    m.definir([pronta, metade, pendente], {metade.pasta: "1"})
    f = FiltroCasos()
    f.setSourceModel(m)
    visiveis = lambda: [f.index(r, 0).data(Qt.UserRole).nome for r in range(f.rowCount())]
    for status, esperado in (("Metade", ["B"]), ("Pronto", ["A"]), ("Pendente", ["C"]), ("", ["A", "B", "C"])):
        f.definir(status=status)
        assert visiveis() == esperado, status


def test_duracao_no_log():
    from sgcor_renov.ui.trabalhador import duracao
    assert [duracao(x) for x in (0.4, 37.6, 60, 65, 754)] == ["0 s", "38 s", "1 min 00 s", "1 min 05 s", "12 min 34 s"]


def test_tema_muda_mesmo_no_estilo_do_windows_10():
    """Q89: o estilo "windowsvista" (padrão do Qt no Windows 10) ignorava o tema escuro."""
    from PySide6.QtGui import QGuiApplication, QPalette

    from sgcor_renov.ui.janela import aplicar_tema, estilo_com_tema
    antes = APP.style().name()
    try:
        APP.setStyle("windowsvista")
        estilo_com_tema(APP)
        assert APP.style().name().lower() == "fusion"
        aplicar_tema("escuro")
        escuro = APP.palette().color(QPalette.Window).lightness()
        aplicar_tema("claro")
        claro = APP.palette().color(QPalette.Window).lightness()
        assert escuro < 80 < claro
    finally:
        QGuiApplication.styleHints().unsetColorScheme()
        APP.setStyle(antes)
