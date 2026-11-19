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


# ---- Q62: Porto, opção combinada que não está na tabela da proposta

def test_porto_a_vista_fora_da_tabela_usa_o_1x_de_outra_forma():
    # caso real (Itapipoca): 1x cartão; a proposta só tem 1x boleto, que é o mesmo à vista (−5%)
    c = _caso(ler_porto(PORTO), parcelas=1, forma="cartao")
    assert c.status == "Pronto"
    assert (c.premio_total, c.iof, c.premio_liquido) == (D("1020.11"), D("70.11"), D("950.00"))
    assert any("regra da Porto" in a and "à vista" in a for a in c.avisos)
    assert _caso(ler_porto(PORTO), parcelas=1, forma="debito").premio_total == D("1020.11")


def test_porto_cartao_porto_a_vista_tem_mais_5_por_cento():
    c = _caso(ler_porto(PORTO), parcelas=1, forma="cartao_porto")   # base: 12x Cartão Porto (950,00 + 70,11)
    assert c.status == "Pronto"
    assert (c.premio_liquido, c.iof, c.premio_total) == (D("902.50"), D("66.60"), D("969.10"))


def test_porto_parcelado_sem_juros_usa_premio_integral_e_com_juros_e_pendencia():
    c = _caso(ler_porto(PORTO), parcelas=3, forma="boleto")
    assert c.status == "Pronto" and (c.premio_total, c.iof, c.premio_liquido) == (D("1073.80"), D("73.80"), D("1000.00"))
    assert _caso(ler_porto(PORTO), parcelas=8, forma="cartao").status == "Pronto"     # cartão sem juros até 10x
    for n, forma in ((7, "boleto"), (11, "cartao"), (8, "debito"), (2, "pix")):     # com juros / PIX só à vista
        c = _caso(ler_porto(PORTO), parcelas=n, forma=forma)
        assert any("não está na tabela" in p for p in c.pendencias), (n, forma)


def test_porto_sem_nenhuma_linha_parecida_calcula_do_demonstrativo():
    # tabela de exemplo da Porto: prêmio 1.810,62 (líquido 1.686,18 + IOF 124,44)
    from sgcor_renov.modelos import Proposta
    from sgcor_renov.regras import porto_fora_da_tabela
    p = Proposta(seguradora="PORTO", premio_liquido=D("1686.18"), iof=D("124.44"), premio_total=D("1810.62"))
    av = porto_fora_da_tabela(p, "cartao", 1)
    assert (av.premio_total, av.iof) == (D("1720.09"), D("118.22"))                  # = 1x da Porto
    cp = porto_fora_da_tabela(p, "cartao_porto", 6)
    assert (cp.premio_total, cp.iof) == (D("1720.09"), D("118.22"))                  # = 6x Cartão Porto
    cp1 = porto_fora_da_tabela(p, "cartao_porto", 1)
    assert cp1.iof == D("112.31") and abs(cp1.premio_total - D("1634.08")) <= D("0.01")
    assert cp.primeira + cp.demais * 5 == cp.premio_total


def test_tokio_nao_usa_a_regra_da_porto():
    from sgcor_renov.regras import porto_fora_da_tabela
    assert porto_fora_da_tabela(ler_tokio(TOKIO), "cartao", 1) is None


# ---- Q63: em qual PDF está a pendência (botões "Abrir acordo"/"Abrir proposta" em amarelo)

@pytest.mark.parametrize("pend, onde", [
    ("Parcelas não combinadas no acordo — perguntar ao consultor", {"acordo"}),
    ("Parcelas ambíguas no acordo: “6 ou 10” — perguntar ao consultor", {"acordo"}),
    ("Forma de pagamento não combinada no acordo — perguntar ao consultor", {"acordo"}),
    ("Acordo não encontrado", {"acordo"}),
    ("Vigência da proposta começa em 05/12/2026, mas a configuração usa 31/12/2026", {"proposta"}),
    ("Proposta: CNPJ do proponente não encontrado", {"proposta"}),
    ("Comissão 9% fora da tabela de bônus", {"proposta"}),
    ("Duas coberturas do mesmo tipo (Incêndio): “A” e “B”", {"proposta"}),
    ("2 propostas na pasta: escolher a final (Q9)", {"proposta"}),
    ("10x boleto não está na tabela de pagamento da proposta", {"acordo", "proposta"}),
    ("O CNPJ citado no acordo é diferente do CNPJ da proposta", {"acordo", "proposta"}),
    ("Forma “x” sem mapeamento para o SGCOR", set()),
])
def test_onde_pendencia(pend, onde):
    from sgcor_renov.regras import onde_pendencia
    assert onde_pendencia(pend) == onde


# ---- Q64: vigência da proposta diferente da padrão, confirmada pelo consultor

def test_vigencia_diferente_e_pendencia_ate_o_consultor_confirmar():
    p = ler_porto(PORTO)
    p.vigencia_inicio = "05/12/2026"
    c = Caso(seguradora="PORTO", pasta=Path("."), nome="X", proposta=p, escolha=Escolha(parcelas=6, forma="boleto"))
    assert any(t.startswith("Vigência da proposta") for t in aplicar(c, CFG).pendencias)

    p2 = ler_porto(PORTO)
    p2.vigencia_inicio = "05/12/2026"
    c2 = Caso(seguradora="PORTO", pasta=Path("."), nome="X", proposta=p2, escolha=Escolha(parcelas=6, forma="boleto"),
              vigencia_confirmada="05/12/2026")
    aplicar(c2, CFG)
    assert not any(t.startswith("Vigência") for t in c2.pendencias)
    assert any("confirmou" in a and CFG.vigencia_inicio in a for a in c2.avisos)

    # confirmou outra data (a proposta mudou depois) → volta a ser pendência
    p3 = ler_porto(PORTO)
    p3.vigencia_inicio = "10/12/2026"
    c3 = Caso(seguradora="PORTO", pasta=Path("."), nome="X", proposta=p3, escolha=Escolha(parcelas=6, forma="boleto"),
              vigencia_confirmada="05/12/2026")
    assert any(t.startswith("Vigência da proposta") for t in aplicar(c3, CFG).pendencias)
