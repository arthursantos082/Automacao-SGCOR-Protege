from decimal import Decimal as D

from amostras import PORTO, TOKIO
from sgcor_renov.propostas import classificar, ler_porto, ler_tokio


def test_classificacao_pelo_conteudo():
    assert classificar(TOKIO) == "PROPOSTA_TOKIO"
    assert classificar(PORTO) == "PROPOSTA_PORTO"
    assert classificar("Histórico de Atendimento\nContato Atendente") == "ACORDO"
    assert classificar("E-mail de Grupo Protege - PROPOSTA\nhttps://mail.google.com/mail/u/0/") == "ACORDO_EMAIL"
    assert classificar("qualquer outra coisa") == "DESCONHECIDO"


def test_tokio_campos_principais():
    p = ler_tokio(TOKIO)
    assert p.problemas == []
    assert p.numero == "15800001"
    assert p.apolice_anterior == "1234567"          # zeros à esquerda removidos
    assert p.cnpj == "11222333000181"                # não pega o CNPJ da própria Tokio
    assert p.razao_social == "LOTERICA EXEMPLO LTDA"
    assert (p.premio_liquido, p.iof, p.premio_total) == (D("1000.00"), D("73.80"), D("1073.80"))
    assert p.comissao == 21


def test_tokio_opcoes_somam_plano():
    p = ler_tokio(TOKIO)
    por_desc = {(o.forma, o.parcelas): o for o in p.opcoes}
    assert por_desc[("boleto", 1)].descricao.endswith("À VISTA")
    assert ("boleto", 6) in por_desc and por_desc[("boleto", 6)].marcada
    assert ("boleto", 10) in por_desc                # 1+9 e 0+10 → 10 (Q13)
    assert ("debito_pix", 6) in por_desc
    assert ("cartao", 10) in por_desc


def test_porto_campos_principais():
    p = ler_porto(PORTO)
    assert p.problemas == []
    assert p.numero == "118600001"
    assert p.apolice_anterior == "4000001"
    assert p.cnpj == "11222333000181"
    assert p.vigencia_inicio == "31/12/2026" and p.vigencia_fim == "31/12/2027"
    assert p.comissao == 20
    assert p.premio_total == D("1073.80")


def test_porto_valores_mudam_com_a_forma():
    """À vista e cartão Porto têm desconto e IOF próprio: o total é a soma das parcelas daquela forma."""
    p = ler_porto(PORTO)
    op = {(o.forma, o.parcelas): o for o in p.opcoes}
    a_vista = op[("boleto", 1)]
    assert a_vista.premio_total == D("1020.11")
    assert a_vista.iof == D("70.11")
    assert a_vista.premio_liquido == D("950.00")
    seis = op[("boleto", 6)]
    assert seis.premio_total == D("178.98") + 5 * D("178.96")
    assert op[("cartao_porto", 12)].iof == D("70.11")
    assert op[("cartao", 10)].forma == "cartao"
