"""Leitura de PDFs: texto corrido e linhas com posição horizontal."""
from __future__ import annotations

import re
import sys
import types
from dataclasses import dataclass
from pathlib import Path

from .caminhos import longo


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


class PdfImagem(Exception):
    """Q87: o PDF é só imagem (impresso pela "Microsoft Print to PDF", print de tela, escaneado): não tem texto."""


def so_imagem(caminho: Path, paginas: int = 2) -> bool:
    """Q87: nenhum caractere de texto nas primeiras páginas. Pelo pdfium (o mesmo que o pdfplumber usa para desenhar
    as páginas): ~0,1 s. O pdfplumber levava ~1 min para concluir que uma proposta escaneada de 12 páginas não tem
    texto. Erro ao abrir → False (a leitura normal mostra o erro dela)."""
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(longo(caminho))
    except Exception:
        return False
    try:
        if len(doc) == 0:
            return False
        for i in range(min(paginas, len(doc))):
            pg = doc[i]
            tp = pg.get_textpage()
            try:
                if tp.get_text_range().strip():
                    return False
            finally:
                tp.close()
                pg.close()
        return True
    except Exception:
        return False
    finally:
        doc.close()


PAGINAS_SEMPRE_INTEIRO = 20
_CAB_TOKIO = ("COTAÇÃO DE SEGURO TOKIO MARINE", "PROPOSTA DE SEGURO TOKIO MARINE")
_CONTADOR = re.compile(r"\s1 / (\d+)\s")
_CAB_LER_INTEIRO = re.compile(r"HIST[ÓO]RICO DE ATENDIMENTO|N[ÚU]MERO DO OR[ÇC]AMENTO|MAIL\.GOOGLE\.COM|^\s*E-MAIL DE ",
                              re.M)


def paginas_uteis(caminho: Path) -> int | None:
    """Q88: quantas páginas do começo bastam (None = todas). As apólices têm ~190 páginas e algumas cotações da Tokio
    vêm com as condições gerais anexadas (~140); o pdfplumber leva ~0,2 s por página e lia tudo (até 15 min numa
    pasta). Pelo pdfium (milissegundos):
    - até 20 páginas, ou acordo/orçamento Porto/e-mail na 1ª página → tudo, como sempre;
    - cotação/proposta Tokio → as N páginas do contador "1 / N" da 1ª página (ou as do começo com o cabeçalho);
    - o resto (apólice, condições gerais, boleto…) → 3, só para reconhecer o que é."""
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(longo(caminho))
    except Exception:
        return None
    try:
        n = len(doc)
        if n <= PAGINAS_SEMPRE_INTEIRO:
            return None

        def txt(i: int) -> str:
            pg = doc[i]
            tp = pg.get_textpage()
            try:
                return tp.get_text_range().upper()
            finally:
                tp.close()
                pg.close()
        t0 = txt(0)
        if any(k in t0 for k in _CAB_TOKIO):
            # o rodapé da 1ª página diz quantas páginas tem a cotação/proposta ("1 / 14"); as condições gerais vêm
            # depois. Sem ele: as páginas do começo com o cabeçalho (algumas cotações não o repetem no anexo)
            if (m := _CONTADOR.search(t0)) and 1 <= int(m.group(1)) <= n:
                return int(m.group(1))
            k = 1
            while k < n and any(c in txt(k) for c in _CAB_TOKIO):
                k += 1
            return k
        if _CAB_LER_INTEIRO.search(t0):
            return None
        return 3
    except Exception:
        return None
    finally:
        doc.close()


def texto(caminho: Path, max_paginas: int | None = None, so_uteis: bool = False) -> str:
    """max_paginas: lê só as primeiras (ex.: o CNPJ fica na 1ª página da proposta — Q75).
    so_uteis: lê só as páginas que interessam (Q88, ver paginas_uteis).
    PDF só com imagem → PdfImagem (Q87), na hora."""
    if so_imagem(caminho):
        raise PdfImagem(caminho.name)
    if so_uteis and max_paginas is None:
        max_paginas = paginas_uteis(caminho)
    with pdfplumber.open(longo(caminho)) as doc:
        return "\n".join(p.extract_text() or "" for p in doc.pages[:max_paginas])


def linhas(caminho: Path, tolerancia_y: float = 3.0) -> list[Linha]:
    """Agrupa palavras em linhas por página, guardando o x0 da primeira palavra.

    Palavras com a mesma altura mas em colunas diferentes (gap grande) viram linhas
    separadas, para não misturar a fala do cliente com a do atendente.
    """
    resultado: list[Linha] = []
    with pdfplumber.open(longo(caminho)) as doc:
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
