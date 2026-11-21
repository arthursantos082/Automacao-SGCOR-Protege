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
    assert e.pela_metade_detalhe(pasta) == ("66692", "repasse", "Valor Fixo")      # Q76: mostrado nas Pendências
    e.marcar_pela_metade(pasta, "66692", "anexos", "outro")   # avança a etapa
    assert e.pela_metade(pasta) == ("66692", "anexos")
    e.limpar_pela_metade(pasta)
    assert e.pela_metade(pasta) is None

    destino = pasta.parent / "_CADASTRADOS" / pasta.name
    e.registrar_cadastrada(destino, "LOTERICA EXEMPLO", "TOKIO", "66705", "FULANO", "2026-11-19 11:16:50")
    assert e.cadastradas() == {str(destino): {"nome": "LOTERICA EXEMPLO", "seguradora": "TOKIO",
                                              "proposta_id": "66705", "produtor": "FULANO",
                                              "quando": "2026-11-19 11:16:50"}}
    e.fechar()


def test_vigencia_confirmada_e_estado_antigo_sem_a_coluna(tmp_path):
    import sqlite3
    arq = tmp_path / "estado.sqlite"
    velho = sqlite3.connect(arq)       # estado da 1.1.0: tabela ajustes sem a coluna vigencia
    velho.execute("CREATE TABLE ajustes (pasta TEXT PRIMARY KEY, parcelas INTEGER, forma TEXT, proposta TEXT, "
                  "atualizado TEXT DEFAULT CURRENT_TIMESTAMP)")
    pasta = Path("C:/x/FECHADOS PORTO/LOTERICA EXEMPLO")
    velho.execute("INSERT INTO ajustes (pasta, parcelas) VALUES (?, 6)", (str(pasta),))
    velho.commit(); velho.close()
    e = Estado(arq)
    assert e.ajuste(pasta) == Ajuste(6, None, None, None)
    e.salvar(pasta, Ajuste(6, None, None, "05/12/2026"))
    assert e.ajuste(pasta).vigencia == "05/12/2026"
    assert not Ajuste(vigencia="05/12/2026").vazio()
    assert e.ajuste(pasta).sem_apolice is False
    e.salvar(pasta, Ajuste(6, None, None, "05/12/2026", True))      # Q68
    assert e.ajuste(pasta).sem_apolice is True
    assert not Ajuste(sem_apolice=True).vazio()
    e.fechar()
