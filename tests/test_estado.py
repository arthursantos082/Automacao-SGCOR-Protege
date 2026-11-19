from pathlib import Path

from sgcor_renov.estado import Ajuste, Estado


def test_ajustes_e_renovacao_pela_metade(tmp_path):
    e = Estado(tmp_path / "estado.sqlite")
    pasta = Path("C:/x/FECHADOS TOKIO/LOTERICA EXEMPLO")
    assert e.ajuste(pasta) is None and e.pela_metade(pasta) is None

    e.salvar(pasta, Ajuste(parcelas=6, forma="boleto"))
    assert e.ajuste(pasta) == Ajuste(6, "boleto", None)
    e.salvar(pasta, Ajuste())                      # ajuste vazio apaga
    assert e.ajuste(pasta) is None

    e.marcar_pela_metade(pasta, "66692", "repasse", "Valor Fixo")
    assert e.pela_metade(pasta) == ("66692", "repasse")
    e.marcar_pela_metade(pasta, "66692", "anexos", "outro")   # avança a etapa
    assert e.pela_metade(pasta) == ("66692", "anexos")
    e.limpar_pela_metade(pasta)
    assert e.pela_metade(pasta) is None
    e.fechar()
