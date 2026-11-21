import pytest

from sgcor_renov.acordo import escolha_combinada, mensagens_chat, mensagens_cliente_email
from sgcor_renov.pdftexto import Linha


def test_chat_separa_colunas_e_remove_cabecalhos():
    """Cliente na coluna esquerda (x≈0.06), atendente na coluna do cabeçalho 'Atendente' (aqui x=0.43)."""
    L = lambda top, x, t: Linha(0, top, x, t)  # noqa: E731
    ls = [
        L(70, 0.06, "Histórico de Atendimento"),
        L(80, 0.06, "Contato"), L(80, 0.43, "Atendente"),
        L(90, 0.43, "Consultor Exemplo"), L(95, 0.43, "16/11/2026 ás 11:24:54"),
        L(100, 0.43, "Gostaria de prosseguir em qual forma de pagamento?"),
        L(110, 0.06, "11.222.333/0001-81 LOTERICA EXEMPLO"), L(113, 0.06, "6500000000"),
        L(116, 0.06, "16/11/2026 ás 11:37:13"), L(120, 0.06, "Em 6x sem juros"),
        L(130, 0.06, "11.222.333/0001-81 LOTERICA EXEMPLO"), L(133, 0.06, "6500000000"),
        L(136, 0.06, "16/11/2026 ás 11:38:00"), L(140, 0.06, "no boleto"),
        L(150, 0.43, "Consultor Exemplo"), L(155, 0.43, "16/11/2026 ás 11:40:00"),
        L(160, 0.43, "Perfeito!"),
    ]
    assert mensagens_chat(ls) == [
        ("atendente", "Gostaria de prosseguir em qual forma de pagamento?"),
        ("cliente", "Em 6x sem juros"),
        ("cliente", "no boleto"),
        ("atendente", "Perfeito!"),
    ]

C, A = "cliente", "atendente"


@pytest.mark.parametrize("fala, parcelas", [
    ("Em 6x sem juros", 6),
    ("6 x no boleto", 6),
    ("pode ser em 6 vezes", 6),
    ("05 parcelas", 5),
    ("Pode ser em 1 e mais 5", 6),
    ("1+5", 6), ("1 + 9", 10), ("0+10", 10), ("1+ 9", 10),
    ("Faça à vista", 1), ("Pagamento a vista", 1),
    ("10 X", 10),
    ("pode ser em 10 parcela\ns", 10),
    ("6", 6),
    ("Em 06 no boleto", 6), ("em 10 no cartão", 10), ("Pode ser em 3 pelo pix", 3),   # Q67 (caso real: R J R)
])
def test_formatos_de_parcelas_do_cliente(fala, parcelas):
    assert escolha_combinada([(C, fala)]).parcelas == parcelas


def test_ignora_datas_valores_e_telefones():
    e = escolha_combinada([(C, "Dia 31/12 renova, valor R$ 120.000,00, fone (47) 3027-4100")])
    assert e.parcelas is None


def test_ultima_escolha_do_cliente_vence():
    e = escolha_combinada([(C, "Quero 6x"), (A, "Certo"), (C, "Mudei de ideia, 10x no boleto")])
    assert (e.parcelas, e.forma, e.origem) == (10, "boleto", "cliente")


def test_duas_opcoes_na_mesma_fala_e_ambigua():
    e = escolha_combinada([(C, "6x ou 10x?")])
    assert e.ambigua and e.parcelas is None


def test_oferta_do_consultor_aceita_pelo_cliente():
    e = escolha_combinada([
        (A, "Podemos prosseguir com a renovação do seu seguro em 1+5x no boleto sem juros?"),
        (C, "Bom dia.. Pode sim.."),
    ])
    assert (e.parcelas, e.forma, e.origem) == (6, "boleto", "oferta aceita")


@pytest.mark.parametrize("resposta", ["\uf087", "\uf164", "👍", "👍🏽", " 👍👍 ", "👌", "✅"])
def test_oferta_aceita_so_com_emoji_positivo(resposta):
    # Q63, caso real (Bom Jesus): o cliente respondeu só com 👍; no PDF do chat ele vem como U+F087 (Font Awesome)
    e = escolha_combinada([(A, "Podemos seguir em 10x no boleto sem juros?"), (C, resposta)])
    assert (e.parcelas, e.forma, e.origem) == (10, "boleto", "oferta aceita")
    assert "\uf087" not in e.trecho_parcelas


@pytest.mark.parametrize("resposta", ["😢", "\uf088", "🤔 vou ver", "👎", ".", "!", "...", "!!", "️", "👍 vou ver"])
def test_outros_emojis_nao_aceitam(resposta):
    e = escolha_combinada([(A, "Podemos seguir em 10x no boleto sem juros?"), (C, resposta)])
    assert e.parcelas is None


def test_oferta_so_com_parcelas_aceita_com_pergunta_no_meio():
    # Q70, caso real (WALDINAR): o consultor oferece só "6x", o cliente pergunta da 1ª parcela, o consultor
    # confirma "só dia 10" e o cliente fecha com "Certo" → 6x, forma presumida boleto
    e = escolha_combinada([
        (C, "Certo"),
        (A, "pode renovar em 6x?"),
        (C, "Mas a primeira em janeiro né"),
        (A, "isso só dia 10"),
        (C, "Certo"),
    ])
    assert (e.parcelas, e.forma, e.forma_presumida, e.origem) == (6, "boleto", True, "oferta aceita")
    assert "pode renovar em 6x?" in e.trecho_parcelas and "Certo" in e.trecho_parcelas


def test_oferta_sem_forma_usa_a_forma_que_o_cliente_ja_citou():
    e = escolha_combinada([(C, "prefiro no cartão"), (A, "Vamos fechar em 10x?"), (C, "Pode sim")])
    assert (e.parcelas, e.forma, e.forma_presumida) == (10, "cartao", False)


def test_sem_aceite_a_oferta_nao_vale():
    e = escolha_combinada([(A, "pode renovar em 6x?"), (C, "Mas a primeira em janeiro né")])
    assert e.parcelas is None


def test_cliente_contraproposta_vence_a_oferta():
    e = escolha_combinada([
        (A, "Vamos seguir com a renovação em 1+5x no boleto sem juros?"),
        (C, "Ok, pode renovar, obrigada 1+6"),
    ])
    assert (e.parcelas, e.origem) == (7, "cliente")


def test_ambiguidade_resolvida_por_oferta_aceita():
    e = escolha_combinada([
        (C, "Boleto"), (C, "4 ou 5"),
        (A, "Podemos seguir em 1+5x no boleto sem juros?"), (C, "Sim"),
    ])
    assert (e.parcelas, e.ambigua, e.forma) == (6, False, "boleto")


def test_pergunta_sobre_cartao_nao_muda_forma_combinada_depois():
    e = escolha_combinada([
        (C, "Então 6x no boleto"),
        (C, "Como consigo um cartão de crédito Porto seguro para mim"),
        (A, "Vou prosseguir com a renovação do seu Seguro Lotérico em 6x sem juros no boleto, certo?"),
        (C, "Certo"),
    ])
    assert (e.parcelas, e.forma) == (6, "boleto")


def test_forma_nao_citada_vira_boleto_presumido():
    e = escolha_combinada([(C, "Em 6x sem juros"),
                           (A, "Perfeito, assim que a apólice e os boletos estiverem disponíveis, realizarei o envio!")])
    assert (e.forma, e.forma_presumida) == ("boleto", True)


@pytest.mark.parametrize("fala, forma", [
    ("10 vezes no cartão porto", "cartao_porto"),
    ("10x no cartão de crédito", "cartao"),
    ("Podemos parcelar em 10 vezes débito em conta?", "debito"),
    ("6x no pix", "pix"),
])
def test_formas(fala, forma):
    assert escolha_combinada([(C, fala)]).forma == forma


def test_sem_combinacao_fica_vazio():
    e = escolha_combinada([(C, "Ver cotação"), (A, "Segue cotação.")])
    assert e.parcelas is None and e.forma is None


def test_email_impresso_pega_resposta_do_cliente():
    txt = """E-mail de Grupo Protege - PROPOSTA DE SEGURO LOTÉRICO ... https://mail.google.com/mail/u/0/
Consultor <consultor@grupoprotege.com.br>
PROPOSTA DE SEGURO LOTÉRICO - LOTERICA EXEMPLO
cliente@exemplo.com <cliente@exemplo.com> 13 de novembro de 2026 às 18:06
Para: Consultor <consultor@grupoprotege.com.br>
Boa tarde,
Favor enviar os boletos em 6 vezes.
De: Consultor <consultor@grupoprotege.com.br>
Segue proposta em 1+9.
"""
    msgs = mensagens_cliente_email(txt)
    assert len(msgs) == 1 and "6 vezes" in msgs[0] and "1+9" not in msgs[0]
    assert escolha_combinada([(C, m) for m in msgs]).parcelas == 6


@pytest.mark.parametrize("fala", ["em 06/01 no boleto", "em 2026 no boleto", "Fico em 15 no boleto"])
def test_em_n_no_boleto_nao_confunde_datas_e_numeros_grandes(fala):
    # "em 06/01" é data; 2026 e 15 não são parcelas (1 a 12)
    assert escolha_combinada([(C, fala)]).parcelas is None


# ---- Q74: afirmação do consultor vale sozinha; só a pergunta espera o aceite do cliente

@pytest.mark.parametrize("conversa, parcelas, forma", [
    ([(C, "pode ser"), (A, "Irei prosseguir com a renovação do seu seguro em 6 parcelas no boleto")], 6, "boleto"),
    ([(A, "Irei prosseguir com a renovação do seu seguro em 10 parcelas no cartão de crédito"), (C, "obrigado")],
     10, "cartao"),
    ([(A, "Irei prosseguir com a renovação do seu seguro em 1+5 no boleto")], 6, "boleto"),
    ([(A, "Perfeito, irei prosseguir com a renovação do seu seguro à vista no cartão de crédito")], 1, "cartao"),
])
def test_afirmacao_do_consultor_vale_sozinha(conversa, parcelas, forma):
    e = escolha_combinada(conversa)
    assert (e.parcelas, e.forma, e.origem) == (parcelas, forma, "confirmação do consultor")


def test_pergunta_do_consultor_continua_esperando_aceite():
    assert escolha_combinada([(A, "Posso prosseguir em 6 parcelas no boleto?")]).parcelas is None
    e = escolha_combinada([(A, "Posso prosseguir em 6 parcelas no boleto?"), (C, "pode")])
    assert (e.parcelas, e.origem) == (6, "oferta aceita")


def test_ate_n_vezes_nao_e_fechamento_e_cliente_depois_vence():
    assert escolha_combinada([(A, "No cartão dá para parcelar em até 10x sem juros")]).parcelas is None
    e = escolha_combinada([(A, "Irei prosseguir com a renovação em 6 parcelas no boleto"), (C, "prefiro 10x no cartão")])
    assert (e.parcelas, e.forma, e.origem) == (10, "cartao", "cliente")
