"""Leitura de PDFs: texto corrido e linhas com posição horizontal."""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from pathlib import Path


def _garantir_cryptography() -> str | None:
    """Q78: o pdfminer importa o `cryptography` logo de cara, mas só o usa para PDF protegido (AES). Se a parte
    compilada dele ("cryptography/hazmat/bindings/_rust") não carregar numa máquina, TODA leitura de PDF falhava.
    Aqui, se não carregar, entra um substituto: os PDFs normais (todos os nossos) continuam sendo lidos e só um PDF
    protegido dá erro. Devolve a mensagem do erro original (para o log), ou None se carregou."""
    try:
        from cryptography.hazmat.backends import default_backend  # noqa: F401
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes  # noqa: F401
        return None
    except Exception as e:  # ex.: "DLL load failed while importing _rust: …"
        erro = f"{type(e).__name__}: {e}"

    class _PdfProtegido:
        def __init__(self, *a, **k):
            raise RuntimeError(f"PDF protegido: precisa do componente de criptografia, que não carregou nesta "
                               f"máquina ({erro})")

    class _Qualquer(types.ModuleType):
        def __getattr__(self, nome):
            return _PdfProtegido

    for nome in list(sys.modules):          # tira o que ficou pela metade da tentativa
        if nome == "cryptography" or nome.startswith("cryptography."):
            del sys.modules[nome]
    for nome in ("cryptography", "cryptography.hazmat", "cryptography.hazmat.primitives"):
        m = types.ModuleType(nome)
        m.__path__ = []                     # é "pacote": permite os submódulos abaixo
        sys.modules[nome] = m
    backends = types.ModuleType("cryptography.hazmat.backends")
    backends.default_backend = lambda: None
    sys.modules["cryptography.hazmat.backends"] = backends
    ciphers = _Qualquer("cryptography.hazmat.primitives.ciphers")
    ciphers.Cipher = _PdfProtegido
    ciphers.algorithms = _Qualquer("algorithms")
    ciphers.modes = _Qualquer("modes")
    sys.modules["cryptography.hazmat.primitives.ciphers"] = ciphers
    return erro


ERRO_CRIPTOGRAFIA = _garantir_cryptography()

import pdfplumber  # noqa: E402  (depois do substituto do cryptography, se precisar)


@dataclass
class Linha:
    pagina: int
    top: float
    x0: float          # fração da largura da página (0–1)
    texto: str


def texto(caminho: Path, max_paginas: int | None = None) -> str:
    """max_paginas: lê só as primeiras (ex.: o CNPJ fica na 1ª página da proposta — Q75)."""
    with pdfplumber.open(caminho) as doc:
        return "\n".join(p.extract_text() or "" for p in doc.pages[:max_paginas])


def linhas(caminho: Path, tolerancia_y: float = 3.0) -> list[Linha]:
    """Agrupa palavras em linhas por página, guardando o x0 da primeira palavra.

    Palavras com a mesma altura mas em colunas diferentes (gap grande) viram linhas
    separadas, para não misturar a fala do cliente com a do atendente.
    """
    resultado: list[Linha] = []
    with pdfplumber.open(caminho) as doc:
        for n, page in enumerate(doc.pages):
            largura = page.width
            palavras = sorted(page.extract_words(keep_blank_chars=False), key=lambda w: (round(w["top"]), w["x0"]))
            atual: list[dict] = []
            for w in palavras:
                if atual:
                    mesma_linha = abs(w["top"] - atual[-1]["top"]) <= tolerancia_y
                    perto = w["x0"] - atual[-1]["x1"] < largura * 0.08
                    if mesma_linha and perto:
                        atual.append(w)
                        continue
                    resultado.append(_fechar(n, atual, largura))
                atual = [w]
            if atual:
                resultado.append(_fechar(n, atual, largura))
    resultado.sort(key=lambda l: (l.pagina, round(l.top), l.x0))
    return resultado


def _fechar(pagina: int, palavras: list[dict], largura: float) -> Linha:
    return Linha(
        pagina=pagina,
        top=palavras[0]["top"],
        x0=palavras[0]["x0"] / largura,
        texto=" ".join(w["text"] for w in palavras),
    )
