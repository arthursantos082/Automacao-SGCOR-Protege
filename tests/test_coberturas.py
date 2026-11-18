import pytest

from sgcor_renov.coberturas import Dicionario, _linhas_da_pagina, normalizar

DIC = Dicionario.carregar()


@pytest.mark.parametrize("nome, origem, chave", [
    # Tokio
    ("Valores No Interior Do Estabelecimento - Lotérica", "tokio", "valores_interior"),
    ("Valores Em Trânsito - Lotérica", "tokio", "valores_transito"),
    ("Incêndio, Raio, Explosão, Implosão, Fumaça E Queda De Aeronaves", "tokio", "incendio"),
    ("Responsabilidade Civil Operações", "tokio", "rc_operacoes"),
    ("Danos Morais Em Decorrência De Responsabilidade Civil Operações", "tokio", "danos_morais"),
    ("Despesas De Aluguel Em Decorrência De Incêndio, Raio, Explosão", "tokio", "aluguel"),
    # Porto
    ("SUBTRAÇÃO DE VALORES", "porto", "valores_interior"),          # Q48
    ("RESPONSABILIDADE CIVIL", "porto", "rc"),                      # Q49
    ("RESPONSABILIDADE CIVIL EMPREGADOR", "porto", "rc_empregador"),  # início mais longo vence
    ("RESPONSABILIDADE CIVIL DANOS MORAIS", "porto", "danos_morais"),
    ("DESPESAS FIXAS", "porto", "lucros_cessantes"),                # Q50
    ("PERDA OU PAGAMENTO DE ALUGUEL", "porto", "aluguel"),
    # SGCOR (com o código na frente, como vem no select)
    ("456 - GERPA - SUB. DE VALORES NO INTERIOR DO ESTABELECIMENTO", "sgcor", "valores_interior"),
    ("778 - 7\tGERPA - SUB. DE VALORES FORA DO ESTABELECIMENTO", "sgcor", "valores_transito"),
    ("RESPONSABILIDADE CIVIL", "sgcor", "rc"),
    ("RESPONSABILIDADE CIVIL OPERAÇÕES", "sgcor", "rc_operacoes"),
    ("LUCROS CESSANTES (DESPESAS FIXAS), EM DECORRÊNCIA ...", "sgcor", "lucros_cessantes"),
    ("PERDA DE ALUGUEL", "sgcor", "aluguel"),
])
def test_tipo_de(nome, origem, chave):
    t = DIC.tipo_de(nome, origem)
    assert t is not None and t.chave == chave


def test_sem_equivalencia():
    assert DIC.tipo_de("GERENCIAMENTO DE CRISES", "sgcor") is None
    assert DIC.tipo_de("Cobertura inventada", "tokio") is None


def test_normalizar():
    assert normalizar("Incêndio, Raio — Explosão!") == "INCENDIO RAIO EXPLOSAO"


class _Pagina:
    def __init__(self, palavras):
        self._p = palavras

    def extract_words(self):
        return self._p


def _w(texto, x0, top):
    return {"text": texto, "x0": x0, "x1": x0 + 6 * len(texto), "top": top}


def test_colunas_tokio_franquia_nao_vira_lmi():
    """Na Tokio o mínimo da franquia (x≈389) fica perto do LMI (x≈325): só o 1º R$ antes da coluna conta."""
    p = _Pagina([
        _w("Valores", 34, 341), _w("No", 70, 341), _w("Interior", 85, 341), _w("Do", 119, 341),
        _w("R$", 325, 341), _w("30.000,00", 340, 341), _w("20%", 389, 341),
        _w("Estabelecimento", 34, 354), _w("-", 109, 354), _w("Lotérica", 115, 354),
        _w("R$", 389, 354), _w("3.500,00", 405, 354),
    ])
    ls = _linhas_da_pagina(p, x_lmi=227, x_dir=396, top_ini=300, top_fim=400)
    assert [(l.nome, l.lmi) for l in ls] == [("Valores No Interior Do", "R$ 30.000,00"),
                                            ("Estabelecimento - Lotérica", "")]


def test_colunas_porto_ordena_palavras_da_linha():
    """Na Porto um 'Não há.' da coluna P.O.S. fica 1pt acima da linha da cobertura; não pode entrar no nome."""
    p = _Pagina([
        _w("Não", 472, 166.2), _w("há.", 491, 166.2),
        _w("PERDA", 12, 167.4), _w("OU", 43, 167.4), _w("PAGAMENTO", 60, 167.4), _w("DE", 114, 167.4),
        _w("ALUGUEL", 130, 167.4), _w("R$", 256, 167.4), _w("15.000,00", 271, 167.4),
        _w("R$", 328, 167.4), _w("17,91", 343, 167.4),
    ])
    ls = _linhas_da_pagina(p, x_lmi=273, x_dir=334, top_ini=100, top_fim=200)
    assert [(l.nome, l.lmi) for l in ls] == [("PERDA OU PAGAMENTO DE ALUGUEL", "R$ 15.000,00")]
