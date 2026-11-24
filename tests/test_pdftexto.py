import builtins
import importlib
import sys

import pytest


def test_sem_cryptography_os_pdfs_normais_continuam_sendo_lidos(monkeypatch):
    """Q78: se "cryptography/hazmat/bindings/_rust" não carregar (DLL), o pdfminer ainda abre PDFs sem proteção."""
    import_original = builtins.__import__

    def import_falhando(nome, *a, **k):
        # como na máquina com problema: o cryptography de verdade não carrega; o que já está em sys.modules
        # (o substituto) carrega normalmente
        if nome.startswith("cryptography") and nome not in sys.modules:
            raise ImportError("DLL load failed while importing _rust: teste")
        return import_original(nome, *a, **k)

    salvos = {n: m for n, m in sys.modules.items() if n.split(".")[0] in ("cryptography", "pdfminer", "pdfplumber")
              or n == "sgcor_renov.pdftexto"}
    for n in salvos:
        del sys.modules[n]
    monkeypatch.setattr(builtins, "__import__", import_falhando)
    try:
        pdftexto = importlib.import_module("sgcor_renov.pdftexto")
        assert pdftexto.ERRO_CRIPTOGRAFIA and "_rust" in pdftexto.ERRO_CRIPTOGRAFIA
        monkeypatch.setattr(builtins, "__import__", import_original)
        import pdfminer.pdfdocument as pd                                   # carrega com o substituto
        with pytest.raises(RuntimeError, match="PDF protegido"):
            pd.Cipher(pd.algorithms.AES(b"x"), pd.modes.CBC(b"y"), backend=pd.default_backend())
    finally:
        monkeypatch.setattr(builtins, "__import__", import_original)
        for n in [n for n in sys.modules if n.split(".")[0] in ("cryptography", "pdfminer", "pdfplumber")
                  or n == "sgcor_renov.pdftexto"]:
            del sys.modules[n]
        sys.modules.update(salvos)
        import sgcor_renov                       # o pacote também guarda o submódulo como atributo
        if "sgcor_renov.pdftexto" in salvos:
            sgcor_renov.pdftexto = salvos["sgcor_renov.pdftexto"]


def test_com_cryptography_nao_muda_nada():
    from sgcor_renov import pdftexto
    assert pdftexto.ERRO_CRIPTOGRAFIA is None


def _pdf_com_texto(arq):
    """PDF mínimo com uma linha de texto (Helvetica)."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 100] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>", None,
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    fluxo = b"BT /F1 12 Tf 20 50 Td (PROPOSTA DE SEGURO) Tj ET"
    objs[3] = b"<< /Length %d >>\nstream\n" % len(fluxo) + fluxo + b"\nendstream"
    saida, ofs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        ofs.append(len(saida))
        saida += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(saida)
    saida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    saida += b"".join(b"%010d 00000 n \n" % o for o in ofs)
    saida += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    arq.write_bytes(bytes(saida))


def test_pdf_so_imagem_e_detectado_na_hora(tmp_path):
    """Q87: PDF impresso como imagem ("Microsoft Print to PDF") → PdfImagem, sem passar pelo pdfminer (~1 min)."""
    import time

    from PIL import Image

    from sgcor_renov.pdftexto import PdfImagem, so_imagem, texto
    img = tmp_path / "proposta.pdf"
    Image.new("RGB", (1240, 1754), "white").save(img, save_all=True,
                                                  append_images=[Image.new("RGB", (1240, 1754), "white")] * 11)
    com_texto = tmp_path / "texto.pdf"
    _pdf_com_texto(com_texto)
    assert so_imagem(img) and not so_imagem(com_texto)
    t = time.monotonic()
    with pytest.raises(PdfImagem):
        texto(img)
    assert time.monotonic() - t < 1
    assert "PROPOSTA DE SEGURO" in texto(com_texto)
    ruim = tmp_path / "ruim.pdf"
    ruim.write_bytes(b"isto nao e um pdf")
    assert not so_imagem(ruim)                  # erro ao abrir: a leitura normal mostra o erro dela


def test_pagina_so_com_espacos_conta_como_imagem(tmp_path, monkeypatch):
    """Q87: texto só de espaços/quebras (comum em PDF impresso) não é texto de verdade."""
    import pypdfium2 as pdfium

    from sgcor_renov.pdftexto import so_imagem
    arq = tmp_path / "espacos.pdf"
    _pdf_com_texto(arq)
    monkeypatch.setattr(pdfium.PdfTextPage, "get_text_range", lambda self, *a, **k: " \r\n \n ")
    assert so_imagem(arq)


def _pdf_paginas(arq, textos):
    """PDF mínimo com uma página por texto (Helvetica, só ASCII)."""
    n = len(textos)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n)).encode()
    fonte = 3 + 2 * n
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, n)]
    for i, t in enumerate(textos):
        fluxo = b"BT /F1 12 Tf 20 50 Td (%s) Tj ET" % t.encode()
        objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 100] /Contents %d 0 R "
                    b"/Resources << /Font << /F1 %d 0 R >> >> >>" % (4 + 2 * i, fonte))
        objs.append(b"<< /Length %d >>\nstream\n" % len(fluxo) + fluxo + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    saida, ofs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        ofs.append(len(saida))
        saida += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(saida)
    saida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    saida += b"".join(b"%010d 00000 n \n" % o for o in ofs)
    saida += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    arq.write_bytes(bytes(saida))


def test_paginas_uteis(tmp_path):
    """Q88: só o começo que interessa dos PDFs longos (apólice ~190 p., cotação Tokio com condições gerais ~140 p.)."""
    from sgcor_renov.pdftexto import paginas_uteis, texto
    tokio = tmp_path / "tokio.pdf"
    _pdf_paginas(tokio, ["PROPOSTA DE SEGURO TOKIO MARINE p%d" % i for i in range(4)] + ["CONDICOES GERAIS"] * 26)
    assert paginas_uteis(tokio) == 4
    t = texto(tokio, so_uteis=True)
    assert "p3" in t and "CONDICOES" not in t
    assert "CONDICOES" in texto(tokio)                     # sem so_uteis: tudo, como antes
    # "Proposta de Seguro" repete o cabeçalho até nas condições gerais: vale o contador "1 / N" da 1ª página
    prop = tmp_path / "prop.pdf"
    _pdf_paginas(prop, ["PROPOSTA DE SEGURO TOKIO MARINE  %d / 5 " % (i + 1) for i in range(5)]
                 + ["PROPOSTA DE SEGURO TOKIO MARINE CONDICOES GERAIS"] * 25)
    assert paginas_uteis(prop) == 5
    apolice = tmp_path / "apolice.pdf"
    _pdf_paginas(apolice, ["APOLICE"] * 30)
    assert paginas_uteis(apolice) == 3
    acordo = tmp_path / "acordo.pdf"
    _pdf_paginas(acordo, ["HISTORICO DE ATENDIMENTO"] + ["cliente: ok"] * 29)
    assert paginas_uteis(acordo) is None
    curto = tmp_path / "curto.pdf"
    _pdf_paginas(curto, ["APOLICE"] * 20)
    assert paginas_uteis(curto) is None
    assert paginas_uteis(tmp_path / "nao-existe.pdf") is None
