"""Leitura das pastas em segundo plano.

- Só relê a pasta cujo PDF, ajuste ou configuração mudou (cache em memória + em disco, fora do git).
- Pastas a reler são processadas em paralelo (um processo por núcleo): ler PDF custa 1–5 s por lotérica.
"""
from __future__ import annotations

import hashlib
import os
import pickle
import threading
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ..config import RAIZ, Config
from ..estado import Ajuste, pasta_dados
from ..modelos import Caso
from ..scanner import (analisar_pasta, assinatura, cnpj_da_pasta, marcar_ja_cadastradas, pastas_de,
                       seguradora_da_pasta, soltos)

VERSAO_LEITURA = "17"   # aumentar quando a lógica de leitura mudar, para invalidar o cache em disco


def _versao() -> str:
    h = hashlib.sha1(VERSAO_LEITURA.encode())
    for f in sorted((RAIZ / "config").glob("*.toml")):
        h.update(f.read_bytes())
    return h.hexdigest()


def _analisar(pasta: Path, seg: str, cfg: Config, ajuste: Ajuste | None) -> Caso:
    return analisar_pasta(pasta, seg, cfg, ajuste)


class Leitor(QObject):
    progresso = Signal(int, int, str)     # atual, total, nome
    concluido = Signal(object)            # list[Caso]
    erro = Signal(str)

    def __init__(self, cfg: Config, arquivo_cache: Path | None = None):
        super().__init__()
        self.cfg = cfg
        self.arquivo_cache = arquivo_cache or pasta_dados() / "cache-leitura.pickle"
        self.versao = _versao()
        self._cache: dict[Path, tuple[tuple, tuple, Caso]] = {}
        self._cad: dict[Path, tuple[tuple, str | None]] = {}    # Q75: pasta em _CADASTRADOS → (assinatura, CNPJ)
        self._carregar_cache()
        self.cancelar = threading.Event()   # setado ao fechar o app: para de esperar as pastas restantes

    def _carregar_cache(self) -> None:
        try:
            dados = pickle.loads(self.arquivo_cache.read_bytes())
            if dados.get("versao") == self.versao:
                self._cache = dados["casos"]
                self._cad = dados.get("cadastradas", {})
        except Exception:
            pass

    def _salvar_cache(self) -> None:
        try:
            tmp = self.arquivo_cache.with_suffix(".tmp")
            tmp.write_bytes(pickle.dumps({"versao": self.versao, "casos": self._cache, "cadastradas": self._cad}))
            os.replace(tmp, self.arquivo_cache)
        except Exception:
            pass  # cache é só otimização

    def ler(self, raizes: list[Path], ajustes: dict[Path, Ajuste]) -> None:
        """Roda na thread do leitor. ajustes é uma cópia feita na thread da tela (SQLite não é compartilhado)."""
        try:
            alvos: list[tuple[Path, str]] = []
            soltos_: list[Caso] = []
            for raiz in raizes:
                if not raiz.is_dir():
                    continue
                seg = seguradora_da_pasta(raiz)
                soltos_.extend(soltos(raiz))
                alvos.extend((p, seg) for p in pastas_de(raiz))

            resultado: dict[Path, Caso] = {}
            reler: list[tuple[Path, str, tuple, tuple]] = []
            for pasta, seg in alvos:
                a = ajustes.get(pasta)
                chave_aj = (a.parcelas, a.forma, a.proposta, a.vigencia, a.sem_apolice) if a else ()
                ass = assinatura(pasta)
                hit = self._cache.get(pasta)
                if hit and hit[0] == ass and hit[1] == chave_aj:
                    resultado[pasta] = hit[2]
                else:
                    reler.append((pasta, seg, ass, chave_aj))

            feitos = len(resultado)
            total = len(alvos)
            self.progresso.emit(feitos, total, "")
            if reler:
                trabalhadores = max(1, min(len(reler), (os.cpu_count() or 2) - 1))
                ex = ProcessPoolExecutor(max_workers=trabalhadores)
                try:
                    futuros = {ex.submit(_analisar, p, s, self.cfg, ajustes.get(p)): (p, ass, aj)
                               for p, s, ass, aj in reler}
                    for fut in as_completed(futuros):
                        if self.cancelar.is_set():
                            break
                        pasta, ass, aj = futuros[fut]
                        caso = fut.result()
                        self._cache[pasta] = (ass, aj, caso)
                        resultado[pasta] = caso
                        feitos += 1
                        self.progresso.emit(feitos, total, pasta.name)
                finally:
                    # ao fechar o app: descarta o que ainda não começou e não espera as pastas restantes
                    ex.shutdown(wait=not self.cancelar.is_set(), cancel_futures=True)
                if self.cancelar.is_set():
                    self._salvar_cache()   # guarda o que já foi lido
                    return

            vivos = {p for p, _ in alvos}
            for velho in set(self._cache) - vivos:
                del self._cache[velho]
            cadastradas = self._ler_cadastradas(raizes)
            self._salvar_cache()
            casos = marcar_ja_cadastradas([resultado[p] for p, _ in alvos], cadastradas)
            self.concluido.emit(soltos_ + casos)
        except Exception as e:  # nunca derrubar a tela por causa de um PDF
            self.erro.emit(f"{type(e).__name__}: {e}")

    def _ler_cadastradas(self, raizes: list[Path]) -> dict[Path, str | None]:
        """Q75: CNPJ de cada pasta em _CADASTRADOS (do nome ou da proposta), com cache — só relê a pasta nova/mudada."""
        pastas = [p for r in raizes if (r / "_CADASTRADOS").is_dir() for p in (r / "_CADASTRADOS").iterdir()
                  if p.is_dir()]
        assin = {p: assinatura(p) for p in pastas}
        reler = [p for p in pastas if p not in self._cad or self._cad[p][0] != assin[p]]
        if reler:
            ex = ProcessPoolExecutor(max_workers=max(1, min(len(reler), (os.cpu_count() or 2) - 1)))
            try:
                for p, cnpj in zip(reler, ex.map(cnpj_da_pasta, reler)):
                    self._cad[p] = (assin[p], cnpj)
            finally:
                ex.shutdown(wait=True)
        for velho in set(self._cad) - set(pastas):
            del self._cad[velho]
        return {p: self._cad[p][1] for p in pastas}
