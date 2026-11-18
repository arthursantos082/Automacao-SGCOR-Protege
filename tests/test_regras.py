from decimal import Decimal as D
from pathlib import Path

import pytest

from amostras import PORTO, TOKIO
from sgcor_renov.config import carregar
from sgcor_renov.modelos import Caso, Escolha
from sgcor_renov.numeros import dinheiro, formatar_dinheiro, mais_um_ano
from sgcor_renov.propostas import ler_porto, ler_tokio
from sgcor_renov.regras import aplicar

CFG = carregar()


@pytest.mark.parametrize("comissao, bonus", [(10, "18.00"), (16, "18.00"), (17, "20.00"), (19, "20.00"),
                                              (20, "30.00"), (23, "30.00"), (24, "40.00"), (32, "40.00")])
def test_tabela_de_bonus(comissao, bonus):
    assert CFG.bonus_para(comissao) == D(bonus)


def _caso(prop, **escolha):
    c = Caso(seguradora=prop.seguradora, pasta=Path("."), nome="X", proposta=prop, escolha=Escolha(**escolha))
    return aplicar(c, CFG)


def test_caso_pronto_tokio():
    c = _caso(ler_tokio(TOKIO), parcelas=10, forma="boleto")
    assert c.status == "Pronto"
    assert (c.cobranca_id, c.bonus, c.premio_total) == (1, D("30.00"), D("1073.80"))
    assert any("marcação (X)" in a for a in c.avisos)


def test_opcao_inexistente_vira_pendencia():
    c = _caso(ler_porto(PORTO), parcelas=10, forma="boleto")
    assert c.status == "Pendente"
    assert any("não está na tabela" in p for p in c.pendencias)


def test_porto_a_vista_usa_valores_da_forma():
    c = _caso(ler_porto(PORTO), parcelas=1, forma="boleto")
    assert (c.premio_total, c.iof, c.premio_liquido) == (D("1020.11"), D("70.11"), D("950.00"))


def test_cartao_porto_mapeia_para_cobranca_25():
    c = _caso(ler_porto(PORTO), parcelas=12, forma="cartao_porto")
    assert c.status == "Pronto" and c.cobranca_id == 25


def test_pix_aceita_opcao_debito_pix_da_tokio():
    c = _caso(ler_tokio(TOKIO), parcelas=6, forma="pix")
    assert c.status == "Pronto" and c.cobranca_id == 36


def test_sem_parcelas_pede_ao_consultor():
    c = _caso(ler_tokio(TOKIO))
    assert any("perguntar ao consultor" in p for p in c.pendencias)


def test_numeros():
    assert dinheiro("1.514,06") == D("1514.06")
    assert formatar_dinheiro(D("1514.06")) == "1.514,06"
    assert mais_um_ano("31/12/2026") == "31/12/2027"
