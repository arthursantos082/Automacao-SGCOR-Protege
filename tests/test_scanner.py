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

    def texto(p: Path, **k) -> str:
        if arquivos[p.name] is None:
            raise ValueError("PDF protegido")
        return arquivos[p.name]

    monkeypatch.setattr(scanner, "texto", texto)
    monkeypatch.setattr(scanner.acordo_mod, "ler_acordo", lambda caminho, tipo: (Escolha(6, "boleto"), set()))
    monkeypatch.setattr(scanner.cob_mod, "ler", lambda caminho, seg, paginas=None: [])
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
    monkeypatch.setattr(scanner.cob_mod, "ler", lambda caminho, seg, paginas=None: [])
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
    monkeypatch.setattr(scanner.cob_mod, "ler", lambda caminho, seg, paginas=None: [])
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


# ---- Q85: _CADASTRADOS na pasta-mãe (ao lado de FECHADOS PORTO e FECHADOS TOKIO), criada se não existir
def test_cadastrados_na_pasta_mae_e_antigas_continuam_lidas(tmp_path):
    from sgcor_renov.estado import Estado
    from sgcor_renov.scanner import lotericas_cadastradas, pastas_cadastrados
    from sgcor_renov.ui.cadastradas import listar
    from sgcor_renov.ui.trabalhador import mover_para_cadastrados

    porto, tokio = tmp_path / "FECHADOS-PORTO", tmp_path / "FECHADOS-TOKIO"
    (porto / "LOTERICA A").mkdir(parents=True)
    (tokio / "LOTERICA B").mkdir(parents=True)
    (porto / "_CADASTRADOS" / "LOTERICA VELHA").mkdir(parents=True)      # de antes da 1.1.8
    assert pastas_cadastrados([porto, tokio]) == [porto / "_CADASTRADOS"]

    destino = mover_para_cadastrados(porto / "LOTERICA A")                # cria a _CADASTRADOS da pasta-mãe
    assert destino == tmp_path / "_CADASTRADOS" / "LOTERICA A" and destino.is_dir()
    assert mover_para_cadastrados(tokio / "LOTERICA B").parent == tmp_path / "_CADASTRADOS"   # a mesma, das duas
    assert not (porto / "LOTERICA A").exists() and not (tokio / "_CADASTRADOS").exists()

    assert pastas_cadastrados([porto, tokio]) == [tmp_path / "_CADASTRADOS", porto / "_CADASTRADOS"]
    assert sorted(p.name for p in lotericas_cadastradas([porto, tokio])) == ["LOTERICA A", "LOTERICA B",
                                                                             "LOTERICA VELHA"]
    e = Estado(tmp_path / "estado.sqlite")
    e.registrar_cadastrada(destino, "LOTERICA A", "PORTO", "66999", "FULANO", "2026-11-23 10:00:00")
    segs = {c.nome: c.seguradora for c in listar([porto, tokio], e)}
    assert segs == {"LOTERICA A": "PORTO", "LOTERICA B": "", "LOTERICA VELHA": "PORTO"}
    e.fechar()


# ---- Q87: PDF salvo como imagem (impresso pela "Microsoft Print to PDF", print do WhatsApp)
IMAGEM = object()


def _pasta_img(tmp_path, monkeypatch, arquivos, ajuste=None):
    from sgcor_renov.pdftexto import PdfImagem
    pasta = tmp_path / "LOTERICA X"
    pasta.mkdir(parents=True)
    for nome in arquivos:
        (pasta / nome).write_bytes(b"%PDF-1.4")

    def texto(p: Path, **k) -> str:
        if arquivos[p.name] is IMAGEM:
            raise PdfImagem(p.name)
        return arquivos[p.name]

    monkeypatch.setattr(scanner, "texto", texto)
    monkeypatch.setattr(scanner.acordo_mod, "ler_acordo", lambda caminho, tipo: (Escolha(6, "boleto"), set()))
    monkeypatch.setattr(scanner.cob_mod, "ler", lambda caminho, seg, paginas=None: [])
    return scanner.analisar_pasta(pasta, "PORTO", CFG, ajuste)


def test_acordo_em_imagem_e_pendencia_ate_o_consultor_informar(tmp_path, monkeypatch):
    from sgcor_renov.estado import Ajuste
    arqs = {"De Acordo - LOTERICA X.pdf": IMAGEM, "X.pdf": PORTO}
    c = _pasta_img(tmp_path / "a", monkeypatch, arqs)
    [p] = [x for x in c.pendencias if x.startswith(scanner.PEND_ACORDO_IMAGEM)]
    assert "De Acordo - LOTERICA X.pdf" in p and c.acordo.name == "De Acordo - LOTERICA X.pdf"
    assert c.escolha is None and not any("Acordo não encontrado" in x for x in c.pendencias)
    # o consultor leu o print e informou no Resolver → segue como as outras
    c = _pasta_img(tmp_path / "b", monkeypatch, arqs, Ajuste(parcelas=6, forma="boleto"))
    assert not any(x.startswith(scanner.PEND_ACORDO_IMAGEM) for x in c.pendencias)
    assert (c.parcelas, c.forma, c.escolha.origem) == (6, "boleto", "consultor")
    assert any(a.startswith(scanner.PEND_ACORDO_IMAGEM) for a in c.avisos)
    # só as parcelas, sem a forma → continua pendente
    c = _pasta_img(tmp_path / "c", monkeypatch, arqs, Ajuste(parcelas=6))
    assert any(x.startswith(scanner.PEND_ACORDO_IMAGEM) for x in c.pendencias)


def test_proposta_em_imagem_pede_o_pdf_original(tmp_path, monkeypatch):
    c = _pasta_img(tmp_path, monkeypatch, {"ACORDO X.pdf": "HISTÓRICO DE ATENDIMENTO ...",
                                           "proposta 04071820000125 X.pdf": IMAGEM})
    [p] = [x for x in c.pendencias if x.startswith(scanner.PEND_PROPOSTA_IMAGEM)]
    assert "baixe o PDF original" in p and "Proposta não encontrada" not in c.pendencias
    assert [x.name for x in c.propostas] == ["proposta 04071820000125 X.pdf"]      # "Abrir proposta" abre a imagem
    assert c.acordo.name == "ACORDO X.pdf"


def test_imagem_sem_nome_conhecido_vale_por_eliminacao(tmp_path, monkeypatch):
    c = _pasta_img(tmp_path / "a", monkeypatch, {"X.pdf": PORTO, "print.pdf": IMAGEM})
    assert c.acordo.name == "print.pdf" and any(x.startswith(scanner.PEND_ACORDO_IMAGEM) for x in c.pendencias)
    c = _pasta_img(tmp_path / "b", monkeypatch, {"ACORDO X.pdf": "HISTÓRICO DE ATENDIMENTO ...", "scan.pdf": IMAGEM})
    assert any(x.startswith(scanner.PEND_PROPOSTA_IMAGEM) for x in c.pendencias)
    # nada em texto e nomes que não dizem nada: não adivinha
    c = _pasta_img(tmp_path / "c", monkeypatch, {"a.pdf": IMAGEM, "b.pdf": IMAGEM})
    assert {"Acordo não encontrado", "Proposta não encontrada"} <= set(c.pendencias)
    assert sum("salvo como imagem" in a for a in c.avisos) == 2
    # os dois em imagem, com nome: os dois viram pendência de imagem
    c = _pasta_img(tmp_path / "d", monkeypatch, {"ACORDO X.pdf": IMAGEM, "COTACAO X.pdf": IMAGEM})
    assert any(x.startswith(scanner.PEND_ACORDO_IMAGEM) for x in c.pendencias)
    assert any(x.startswith(scanner.PEND_PROPOSTA_IMAGEM) for x in c.pendencias)


def test_so_o_acordo_em_imagem_fica_laranja(tmp_path, monkeypatch):
    from sgcor_renov.ui.tabela import LARANJA, VERMELHO, ModeloCasos
    c = _pasta_img(tmp_path, monkeypatch, {"De Acordo X.pdf": IMAGEM, "X.pdf": PORTO})
    m = ModeloCasos()
    assert c.pendencias and m.cor_status(c) == (LARANJA if all(
        x.startswith(scanner.PEND_ACORDO_IMAGEM) for x in c.pendencias) else VERMELHO)
    c.pendencias = [x for x in c.pendencias if x.startswith(scanner.PEND_ACORDO_IMAGEM)]
    assert m.cor_status(c) == LARANJA
    c.pendencias.append("Comissão 99% fora da tabela de bônus")         # outra pendência junto → vermelho
    assert m.cor_status(c) == VERMELHO


def test_imagens_sem_nome_conhecido_combinadas_com_imagem_de_nome_conhecido(tmp_path, monkeypatch):
    # acordo sem nome conhecido + proposta em imagem com nome → as duas reconhecidas
    c = _pasta_img(tmp_path / "a", monkeypatch, {"print.pdf": IMAGEM, "COTACAO X.pdf": IMAGEM})
    assert c.acordo.name == "print.pdf" and [p.name for p in c.propostas] == ["COTACAO X.pdf"]
    # acordo em imagem com nome + proposta sem nome conhecido → as duas reconhecidas
    c = _pasta_img(tmp_path / "b", monkeypatch, {"ACORDO X.pdf": IMAGEM, "scan.pdf": IMAGEM})
    assert c.acordo.name == "ACORDO X.pdf" and [p.name for p in c.propostas] == ["scan.pdf"]
    # 2 imagens sem nome e a proposta em texto: não adivinha qual é o acordo
    c = _pasta_img(tmp_path / "c", monkeypatch, {"X.pdf": PORTO, "a.pdf": IMAGEM, "b.pdf": IMAGEM})
    assert "Acordo não encontrado" in c.pendencias and c.acordo is None
    assert sum("salvo como imagem" in a for a in c.avisos) == 2


def test_acordo_em_png_ou_jpg_e_acordo_em_imagem(tmp_path, monkeypatch):
    """Q88: o acordo salvo como foto/print (PNG, JPG) — antes ficava "Acordo não encontrado" ou, com outro PDF na
    pasta (a apólice), "Parcelas não combinadas"."""
    for i, nome in enumerate(("DE ACORDO LOTERICA X EMAIL .png", "de acordo.JPG")):
        c = _pasta_img(tmp_path / str(i), monkeypatch, {nome: IMAGEM, "X.pdf": PORTO, "Apolice X.pdf": "APÓLICE"})
        [p] = [x for x in c.pendencias if x.startswith(scanner.PEND_ACORDO_IMAGEM)]
        assert nome in p and c.acordo.name == nome
        assert not any("Acordo não encontrado" in x or "Parcelas" in x for x in c.pendencias)
    # foto sem nome de acordo numa pasta que já tem o acordo: só aviso, e "Arquivo" (não "PDF")
    c = _pasta_img(tmp_path / "z", monkeypatch, {"image.png": IMAGEM, "X.pdf": PORTO,
                                                 "ACORDO X.pdf": "HISTÓRICO DE ATENDIMENTO ..."})
    assert "Arquivo ignorado (salvo como imagem, o AutoCOR não lê): image.png" in c.avisos


def test_assinatura_muda_com_a_foto_do_acordo(tmp_path):
    """Q88: pôr/trocar a foto do acordo relê a pasta (o cache em disco usa a assinatura)."""
    (tmp_path / "X.pdf").write_bytes(b"%PDF")
    antes = scanner.assinatura(tmp_path)
    (tmp_path / "DE ACORDO.png").write_bytes(b"png")
    assert scanner.assinatura(tmp_path) != antes
