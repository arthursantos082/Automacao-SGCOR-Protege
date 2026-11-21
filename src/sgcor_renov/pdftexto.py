"""Leitura de PDFs: texto corrido e linhas com posição horizontal."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pdfplumber


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
