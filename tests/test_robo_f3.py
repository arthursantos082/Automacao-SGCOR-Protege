"""F3: leitura das telas depois do Avançar (HTML sintético imitando o SGCOR) e decisões do robô."""
from decimal import Decimal as D
from pathlib import Path

from sgcor_renov.coberturas import Cobertura, Dicionario
from sgcor_renov.config import carregar
from sgcor_renov.modelos import Caso
from sgcor_renov.robo.paginas import (CoberturaSgcor, Parcela, anexos_existentes, conferir_parcelas, itens_da_proposta,
                                      ler_coberturas_item, ler_parcelas, plano_coberturas, url_editar_repasse)

CFG = carregar()
DIC = Dicionario.carregar()


def _grid(linhas: str) -> str:
    return f'<table id="tabled_grid">{linhas}</table>'


def test_coberturas_do_item():
    html = _grid("""
<tr><td><a href="https://x/popup.php?op=propostasItensCoberturas&amp;form=alterar&amp;propostaItemCoberturaId=1&amp;propostaId=9">
<i title="Alterar"></i></a></td><td>10</td>
<td title="GERPA - SUB. DE VALORES NO INTERIOR DO ESTABELECIMENTO">GERPA - SUB. DE VALORES NO INTERIOR DO ESTABELECIM...</td>
<td>30.000,00</td><td>0,00</td><td>1</td><td>0,00</td></tr>""")
    [c] = ler_coberturas_item(html)
    assert (c.nome, c.lmi) == ("GERPA - SUB. DE VALORES NO INTERIOR DO ESTABELECIMENTO", D("30000.00"))
    assert "propostaItemCoberturaId=1&propostaId=9" in c.url_alterar   # &amp; desfeito


def _cob(nome, lmi, chave):
    return (Cobertura(nome, D(lmi)), chave)


def _sg(nome, lmi):
    return CoberturaSgcor(nome, D(lmi), f"popup.php?alterar={nome[:5]}")


def test_plano_ajusta_so_o_que_mudou():
    proposta = [_cob("Valores No Interior Do Estabelecimento - Lotérica", "30000", "valores_interior"),
                _cob("Valores Em Trânsito - Lotérica", "20000", "valores_transito"),
                _cob("Incêndio, Raio, Explosão, Implosão, Fumaça", "60000", "incendio")]
    sgcor = [_sg("GERPA - SUB. DE VALORES NO INTERIOR DO ESTABELECIMENTO", "51460"),
             _sg("GERPA - SUB. DE VALORES FORA DO ESTABELECIMENTO", "20000"),
             _sg("INCÊNDIO, RAIO, EXPLOSÃO, IMPLOSÃO, FUMAÇA E QUEDA DE AERONAVES", "60000"),
             _sg("RESPONSABILIDADE CIVIL", "0")]                                    # LMI 0 sem par: ignora (Q51)
    ajustes, pend, avisos = plano_coberturas(proposta, sgcor, DIC)
    assert pend == [] and avisos == []
    assert [(a.nome_sgcor, a.de, a.para) for a in ajustes] == [
        ("GERPA - SUB. DE VALORES NO INTERIOR DO ESTABELECIMENTO", D("51460"), D("30000"))]


def test_plano_so_mexe_em_incendio_e_valores():
    # Q59: só Incêndio e Valores (interior/trânsito); o resto fica como veio, sem pendência nem aviso
    proposta = [_cob("Danos Elétricos", "5000", "danos_eletricos"), _cob("Coisa nova", "1", None),
                _cob("DESPESAS FIXAS", "5000", "lucros_cessantes"),
                _cob("Incêndio, Raio, Explosão", "90000", "incendio"),
                _cob("Valores Em Trânsito - Lotérica", "20000", "valores_transito")]
    sgcor = [_sg("ROUBO E FURTO MEDIANTE ARROMBAMENTO", "5000"),
             _sg("DANOS ELÉTRICOS", "3000"),
             _sg("LUCROS CESSANTES", "2000"), _sg("LUCROS CESSANTES - DESPESAS FIXAS", "2000"),   # caso real
             _sg("INCÊNDIO, RAIO, EXPLOSÃO, IMPLOSÃO, FUMAÇA E QUEDA DE AERONAVES", "60000"),
             _sg("GERPA - SUB. DE VALORES NO INTERIOR DO ESTABELECIMENTO", "30000")]
    ajustes, pend, avisos = plano_coberturas(proposta, sgcor, DIC)
    assert pend == []
    assert [(a.nome_sgcor, a.de, a.para) for a in ajustes] == [
        ("INCÊNDIO, RAIO, EXPLOSÃO, IMPLOSÃO, FUMAÇA E QUEDA DE AERONAVES", D("60000"), D("90000"))]
    # Valores em trânsito novo na proposta → ignora; Valores no interior sumiu da proposta → mantém (Q57)
    assert len(avisos) == 2
    assert any("ignorada" in a and "Trânsito" in a for a in avisos)
    assert any("mantida" in a and "INTERIOR" in a for a in avisos)


def test_plano_tipo_repetido_no_sgcor_ajusta_so_a_gerpa():
    # Q61, caso real (GODOI & CURVELO): duas de Valores no interior → ajusta a GERPA e segue, sem pendência
    proposta = [_cob("Valores No Interior Do Estabelecimento - Lotérica", "30000", "valores_interior")]
    sgcor = [_sg("SUBTRACAO DE VALORES", "50000"),
             _sg("GERPA - SUB. DE VALORES NO INTERIOR DO ESTABELECIMENTO", "50000")]
    ajustes, pend, avisos = plano_coberturas(proposta, sgcor, DIC)
    assert pend == []
    assert [(a.nome_sgcor, a.para) for a in ajustes] == [
        ("GERPA - SUB. DE VALORES NO INTERIOR DO ESTABELECIMENTO", D("30000"))]
    assert len(avisos) == 1 and "ajusta só “GERPA" in avisos[0]          # a outra não vira "mantida"
    # depois de salvo, a conferência escolhe a mesma e não vê mais nada a ajustar
    sgcor[1] = _sg("GERPA - SUB. DE VALORES NO INTERIOR DO ESTABELECIMENTO", "30000")
    assert plano_coberturas(proposta, sgcor, DIC)[0] == []


def test_plano_tipo_repetido_sem_gerpa_ajusta_a_primeira():
    proposta = [_cob("Incêndio", "90000", "incendio")]
    sgcor = [_sg("INCÊNDIO, RAIO, EXPLOSÃO", "60000"), _sg("INCÊNDIO, EXPLOSÃO, FUMAÇA E QUEDA DE", "60000")]
    ajustes, pend, avisos = plano_coberturas(proposta, sgcor, DIC)
    assert pend == [] and len(avisos) == 1
    assert [a.nome_sgcor for a in ajustes] == ["INCÊNDIO, RAIO, EXPLOSÃO"]


def test_parcelas_com_tabelas_aninhadas_e_conferencia():
    linha = lambda n, v, d: (f'<tr><td><div><table id="tabled_grid"><tr><td>mais</td></tr></table></div></td>'
                             f'<td><span>{n}</span></td><td><span></span></td><td><span>{v}</span></td>'
                             f'<td><span>{d}</span></td><td><span>341,03</span></td></tr>')
    html = _grid("".join(linha(i, "366,19", f"15/{i:02d}/2027") for i in range(1, 7))
                 + linha(7, "366,19", "15/07/2027") + "<tr><td></td><td>2.563,33</td></tr>")
    ps = ler_parcelas(html)
    assert [p.numero for p in ps] == [1, 2, 3, 4, 5, 6, 7]
    caso = Caso(seguradora="TOKIO", pasta=Path("."), nome="X", parcelas=7, premio_total=D("2563.33"))
    assert conferir_parcelas(ps, caso, CFG) == []
    caso.parcelas = 6
    assert any("7 parcela" in e for e in conferir_parcelas(ps, caso, CFG))


def test_conferir_parcelas_vencimento_e_soma():
    caso = Caso(seguradora="TOKIO", pasta=Path("."), nome="X", parcelas=2, premio_total=D("100.00"))
    erros = conferir_parcelas([Parcela(1, D("50"), "10/02/2027"), Parcela(2, D("49"), "10/03/2027")], caso, CFG)
    assert any("1º vencimento" in e for e in erros) and any("Soma" in e for e in erros)
    # Q90: o vencimento conferido é o da seguradora do caso
    caso.premio_total = D("99")
    assert conferir_parcelas([Parcela(1, D("50"), "15/01/2027"), Parcela(2, D("49"), "15/02/2027")], caso, CFG) == []
    caso.seguradora = "PORTO"
    assert any("≠ 11/01/2027" in e for e in conferir_parcelas([Parcela(1, D("50"), "15/01/2027"),
                                                                Parcela(2, D("49"), "15/02/2027")], caso, CFG))


def test_itens_repasse_e_anexos():
    assert itens_da_proposta("popup.php?op=propostasItensCoberturas&amp;form=listar&amp;propostaId=9"
                             "&amp;propostaItemId=61123", "9") == ["61123"]
    html = ("confirmaSwal('Para sua comodidade…', '?op=repasses&amp;form=alterar&amp;propostaRepasseId=71676"
            "&amp;propostaId=9&amp;cadastro=true&amp;parcelas=true')")
    assert url_editar_repasse(html) == ["?op=repasses&form=alterar&propostaRepasseId=71676&propostaId=9"
                                        "&cadastro=true&parcelas=true"]
    anexos = _grid('<tr><td><a href="popup.php?op=anexos&amp;form=alterar&amp;anexoId=1"></a></td><td></td>'
                   '<td>ACORDO</td><td>acordo.pdf</td></tr>')
    assert anexos_existentes(anexos) == {"ACORDO"}


def test_navegacao_atropelada_vai_de_novo(tmp_path):
    """Q95 (caso real CORACAO DE MINAS): 'net::ERR_ABORTED; maybe frame was detached?' deixava a lotérica pela
    metade; agora espera a outra navegação e vai de novo. Outros erros continuam subindo na hora."""
    import pytest
    from sgcor_renov.robo.navegador import Robo

    class Pagina:
        def __init__(self, erros):
            self.erros, self.idas = list(erros), 0

        def goto(self, url, wait_until):
            self.idas += 1
            if self.erros:
                raise Exception(self.erros.pop(0))

        def wait_for_load_state(self, *a, **k):
            pass

    r = Robo(CFG, tmp_path, tmp_path)
    r.page = Pagina(["Page.goto: net::ERR_ABORTED; maybe frame was detached?",
                     'Navigation to "x" is interrupted by another navigation to "y"'])
    r._goto("https://sgcor/anexos")
    assert r.page.idas == 3
    r.page = Pagina(["net::ERR_CONNECTION_TIMED_OUT at https://sgcor"])
    with pytest.raises(Exception, match="TIMED_OUT"):
        r._goto("https://sgcor/anexos")
    assert r.page.idas == 1
    r.page = Pagina(["net::ERR_ABORTED"] * 3)
    with pytest.raises(Exception, match="ERR_ABORTED"):
        r._goto("https://sgcor/anexos")
    assert r.page.idas == 3


def test_driver_do_chrome_que_cai_tenta_de_novo_e_explica(tmp_path, monkeypatch):
    """Q99 (caso real, máquina de operador): 'Connection closed while reading from the driver' ao abrir o Chrome —
    tenta mais uma vez; se cair de novo, a mensagem diz o que fazer. Outros erros sobem na hora, como antes."""
    import pytest
    from sgcor_renov.robo import navegador

    monkeypatch.setattr(navegador.time, "sleep", lambda s: None)
    erros = []

    class Playwright:
        def start(self):
            raise Exception(erros.pop(0))

    def falhar_com(*lista):
        erros[:] = list(lista)

    monkeypatch.setattr(navegador, "sync_playwright", lambda: Playwright())
    caiu = "Connection closed while reading from the driver"
    r = navegador.Robo(CFG, tmp_path / "perfil", tmp_path)

    falhar_com(caiu, caiu)
    with pytest.raises(navegador.FalhaRobo, match="Histórico de proteção"):
        r.abrir()
    assert erros == []                       # tentou 2 vezes

    falhar_com(caiu, "outro erro")           # a 2ª tentativa passa do driver e cai em outra coisa: mostra essa
    with pytest.raises(navegador.FalhaRobo, match="outro erro"):
        r.abrir()

    falhar_com("Executable doesn't exist", caiu)
    with pytest.raises(navegador.FalhaRobo, match="Executable doesn't exist"):
        r.abrir()
    assert erros == [caiu]                   # não tentou de novo
