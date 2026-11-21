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
