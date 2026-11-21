from pathlib import Path

from amostras import PORTO
from sgcor_renov import scanner
from sgcor_renov.config import carregar
from sgcor_renov.modelos import Escolha

CFG = carregar()
APOLICE = "PORTO SEGURO CIA DE SEGUROS GERAIS\nAPÓLICE DE SEGURO EMPRESARIAL\nNº da apólice 0118 ..."


def _pasta(tmp_path, arquivos, monkeypatch):
    """Pasta com PDFs "falsos": o texto de cada um vem do dicionário (sem ler PDF de verdade)."""
    pasta = tmp_path / "LOTERICA X"
    pasta.mkdir()
    for nome in arquivos:
        (pasta / nome).write_bytes(b"%PDF-1.4")

    def texto(p: Path) -> str:
        if arquivos[p.name] is None:
            raise ValueError("PDF protegido")
        return arquivos[p.name]

    monkeypatch.setattr(scanner, "texto", texto)
    monkeypatch.setattr(scanner.acordo_mod, "ler_acordo", lambda caminho, tipo: (Escolha(6, "boleto"), set()))
    monkeypatch.setattr(scanner.cob_mod, "ler", lambda caminho, seg: [])
    return scanner.analisar_pasta(pasta, "PORTO", CFG)


def test_pasta_com_apolice_usa_so_cotacao_e_acordo(tmp_path, monkeypatch):
    # Q69: a pasta passa a vir também com a apólice; ela é ignorada (aviso), sem pendência
    c = _pasta(tmp_path, {"ACORDO X.pdf": "HISTÓRICO DE ATENDIMENTO ...", "X.pdf": PORTO,
                          "APOLICE 2025.pdf": APOLICE, "protegido.pdf": None}, monkeypatch)
    assert c.acordo.name == "ACORDO X.pdf" and c.proposta_escolhida.name == "X.pdf"
    assert not any("PDF" in p or "classificar" in p for p in c.pendencias), c.pendencias
    assert any("ignorado" in a and "APOLICE 2025.pdf" in a for a in c.avisos)
    assert any("ignorado" in a and "protegido.pdf" in a for a in c.avisos)


def test_sem_acordo_continua_pendencia_mesmo_com_outros_pdfs(tmp_path, monkeypatch):
    c = _pasta(tmp_path, {"X.pdf": PORTO, "APOLICE.pdf": APOLICE, "outro.pdf": "qualquer coisa"}, monkeypatch)
    assert "Acordo não encontrado" in c.pendencias


# ---- Q72: nome da pasta com o CNPJ (ou só o CNPJ)

def test_separar_cnpj_do_nome_da_pasta():
    from sgcor_renov.numeros import separar_cnpj
    assert separar_cnpj("LOTERICA X - 11.158.635-0002-19") == ("LOTERICA X", "11158635000219")
    assert separar_cnpj("11158635000219") == ("", "11158635000219")
    assert separar_cnpj("11.158.635 0002-19 LOTERICA X") == ("LOTERICA X", "11158635000219")
    assert separar_cnpj("LOTERICA X LTDA") == ("LOTERICA X LTDA", None)
    assert separar_cnpj("LOTERICA 2026") == ("LOTERICA 2026", None)


def _pasta_nome(tmp_path, nome_pasta, monkeypatch):
    pasta = tmp_path / nome_pasta
    pasta.mkdir()
    for n in ("ACORDO.pdf", "X.pdf"):
        (pasta / n).write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(scanner, "texto", lambda p, **k: "HISTÓRICO DE ATENDIMENTO" if p.name == "ACORDO.pdf" else PORTO)
    monkeypatch.setattr(scanner.acordo_mod, "ler_acordo", lambda caminho, tipo: (Escolha(6, "boleto"), set()))
    monkeypatch.setattr(scanner.cob_mod, "ler", lambda caminho, seg: [])
    return scanner.analisar_pasta(pasta, "PORTO", CFG)


def test_pasta_so_com_cnpj_mostra_o_nome_da_proposta(tmp_path, monkeypatch):
    from sgcor_renov.propostas import ler_porto
    p = ler_porto(PORTO)
    c = _pasta_nome(tmp_path, p.cnpj, monkeypatch)
    assert c.nome == p.razao_social
    assert not any("nome da pasta" in x for x in c.pendencias)


def test_pasta_com_nome_e_cnpj_de_outra_loterica_vira_pendencia(tmp_path, monkeypatch):
    c = _pasta_nome(tmp_path, "LOTERICA X - 11.111.111-0001-11", monkeypatch)
    assert c.nome == "LOTERICA X"
    assert any("CNPJ no nome da pasta" in x for x in c.pendencias)


# ---- Q75: lotérica que já está em _CADASTRADOS e voltou para FECHADOS

def _caso_simples(pasta, cnpj=None):
    from sgcor_renov.modelos import Caso, Proposta
    return Caso(seguradora="PORTO", pasta=pasta, nome=pasta.name,
                proposta=Proposta("PORTO", cnpj=cnpj) if cnpj else None)


def test_ja_cadastrada_pelo_cnpj_ou_pelo_nome():
    raiz = Path("C:/x/FECHADOS PORTO")
    cad = {raiz / "_CADASTRADOS" / "LOTERICA BOA SORTE": "47708611000152",
           raiz / "_CADASTRADOS" / "01.359.3270001-17": "01359327000117",
           raiz / "_CADASTRADOS" / "LOTERICA SENGES (20261119-101500)": None}
    casos = [_caso_simples(raiz / "BOA SORTE NOVA PASTA", "47708611000152"),          # mesmo CNPJ, outro nome
             _caso_simples(raiz / "01.359.3270001-17 - LOTERICA X"),                  # CNPJ só no nome da pasta
             _caso_simples(raiz / "Lotérica Senges"),                                 # mesmo nome (sem acento/caixa)
             _caso_simples(raiz / "LOTERICA NOVA", "11111111000111")]                 # não é duplicada
    out = scanner.marcar_ja_cadastradas(casos, cad)
    dup = [any(p.startswith("Já cadastrada") for p in c.pendencias) for c in out]
    assert dup == [True, True, True, False]
    assert "LOTERICA BOA SORTE" in out[0].pendencias[-1]
    assert casos[0].pendencias == []            # o caso original (do cache) não é alterado


def test_cnpj_da_pasta_pelo_nome_ou_pela_proposta(tmp_path, monkeypatch):
    from sgcor_renov.propostas import ler_porto
    assert scanner.cnpj_da_pasta(tmp_path / "01.359.3270001-17 - X") == "01359327000117"
    pasta = tmp_path / "LOTERICA Y"
    pasta.mkdir()
    for n in ("ACORDO.pdf", "Y.pdf"):
        (pasta / n).write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(scanner, "texto", lambda p, **k: "HISTÓRICO DE ATENDIMENTO" if p.name == "ACORDO.pdf" else PORTO)
    assert scanner.cnpj_da_pasta(pasta) == ler_porto(PORTO).cnpj


# ---- Q80: acordo com CNPJ de outra lotérica do mesmo cliente → "Confirmar a lotérica…"

def _pasta_cnpjs(tmp_path, monkeypatch, cnpjs_acordo, ajuste=None):
    pasta = tmp_path / "LOTERICA EXEMPLO"
    pasta.mkdir(parents=True)
    for n in ("ACORDO.pdf", "X.pdf"):
        (pasta / n).write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(scanner, "texto", lambda p, **k: "HISTÓRICO DE ATENDIMENTO" if p.name == "ACORDO.pdf" else PORTO)
    monkeypatch.setattr(scanner.acordo_mod, "ler_acordo", lambda caminho, tipo: (Escolha(6, "boleto"), set(cnpjs_acordo)))
    monkeypatch.setattr(scanner.cob_mod, "ler", lambda caminho, seg: [])
    return scanner.analisar_pasta(pasta, "PORTO", CFG, ajuste)


def test_cnpj_de_outra_loterica_e_pendencia_ate_confirmar(tmp_path, monkeypatch):
    from sgcor_renov.estado import Ajuste
    from sgcor_renov.propostas import ler_porto
    cnpj = ler_porto(PORTO).cnpj
    c = _pasta_cnpjs(tmp_path / "a", monkeypatch, {"99888777000166"})
    [p] = [x for x in c.pendencias if x.startswith(scanner.PEND_CNPJ_ACORDO)]
    assert "99.888.777/0001-66" in p                                    # mostra o CNPJ que o acordo cita
    c = _pasta_cnpjs(tmp_path / "b", monkeypatch, {"99888777000166"}, Ajuste(cnpj_confirmado=cnpj))
    assert not any(x.startswith(scanner.PEND_CNPJ_ACORDO) for x in c.pendencias)
    assert any("confirmou a lotérica" in a for a in c.avisos)
    # confirmado para outro CNPJ (a proposta da pasta mudou) → volta a pedir
    c = _pasta_cnpjs(tmp_path / "c", monkeypatch, {"99888777000166"}, Ajuste(cnpj_confirmado="11111111000111"))
    assert any(x.startswith(scanner.PEND_CNPJ_ACORDO) for x in c.pendencias)
    # acordo cita o próprio CNPJ (também) → nada a confirmar
    c = _pasta_cnpjs(tmp_path / "d", monkeypatch, {cnpj, "99888777000166"})
    assert not any(x.startswith(scanner.PEND_CNPJ_ACORDO) for x in c.pendencias)
