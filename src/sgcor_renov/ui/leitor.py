"""Leitura das pastas em segundo plano, relendo só as pastas que mudaram."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ..config import Config
from ..estado import Ajuste
from ..modelos import Caso
from ..scanner import analisar_pasta, assinatura, pastas_de, seguradora_da_pasta, soltos


class Leitor(QObject):
    progresso = Signal(int, int, str)     # atual, total, nome
    concluido = Signal(object)            # list[Caso]
    erro = Signal(str)

    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self._cache: dict[Path, tuple[tuple, tuple, Caso]] = {}   # pasta → (assinatura, ajuste, caso)

    def ler(self, raizes: list[Path], ajustes: dict[Path, Ajuste]) -> None:
        """Roda na thread do leitor. ajustes é uma cópia feita na thread da tela (SQLite não é compartilhado)."""
        try:
            alvos: list[tuple[Path, str]] = []
            casos: list[Caso] = []
            for raiz in raizes:
                if not raiz.is_dir():
                    continue
                seg = seguradora_da_pasta(raiz)
                casos.extend(soltos(raiz))
                alvos.extend((p, seg) for p in pastas_de(raiz))
            vivos = set()
            for i, (pasta, seg) in enumerate(alvos, 1):
                self.progresso.emit(i, len(alvos), pasta.name)
                vivos.add(pasta)
                a = ajustes.get(pasta)
                chave_aj = (a.parcelas, a.forma, a.proposta) if a else ()
                ass = assinatura(pasta)
                hit = self._cache.get(pasta)
                if hit and hit[0] == ass and hit[1] == chave_aj:
                    casos.append(hit[2])
                    continue
                caso = analisar_pasta(pasta, seg, self.cfg, a)
                self._cache[pasta] = (ass, chave_aj, caso)
                casos.append(caso)
            for velho in set(self._cache) - vivos:
                del self._cache[velho]
            self.concluido.emit(casos)
        except Exception as e:  # nunca derrubar a tela por causa de um PDF
            self.erro.emit(f"{type(e).__name__}: {e}")
