"""Atualização do AutoCOR pela Release mais nova do GitHub (a partir da 1.1.0).

Ao abrir, o AutoCOR instalado consulta a última Release; se houver versão nova, oferece atualizar: baixa o
AutoCOR.zip, descompacta numa pasta temporária e abre o AutoCOR.exe novo com --instalar (pede administrador),
que substitui o de Program Files (preservando config\\). O app atual fecha para liberar os arquivos.
Nada do consultor é enviado: só um GET público na API de Releases.
"""
from __future__ import annotations

import json
import re
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO_PADRAO = "arthursantos082/Automacao-SGCOR-Protege"
ARQUIVO = "AutoCOR.zip"
CABECALHOS = {"User-Agent": "AutoCOR-atualizador", "Accept": "application/vnd.github+json"}


def versao_tupla(v: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", v)[:3]) or (0,)


@dataclass
class Release:
    versao: str
    url_zip: str
    tamanho: int
    notas: str


def ultima_release(repo: str = REPO_PADRAO, timeout: float = 8) -> Release | None:
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest", headers=CABECALHOS)
    with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310 — URL fixa da API do GitHub
        d = json.load(r)
    asset = next((a for a in d.get("assets", []) if a.get("name") == ARQUIVO), None)
    if not asset:
        return None
    return Release(d.get("tag_name", "").lstrip("v"), asset["browser_download_url"], int(asset.get("size", 0)),
                   d.get("body") or "")


def tem_nova(atual: str, release: Release | None) -> bool:
    return release is not None and versao_tupla(release.versao) > versao_tupla(atual)


def baixar(release: Release, progresso: Callable[[int, int], None], cancelado: Callable[[], bool]) -> Path | None:
    """Baixa e descompacta. Devolve o caminho do AutoCOR.exe novo (ou None se cancelado)."""
    if not release.url_zip.startswith("https://github.com/"):
        raise ValueError("endereço de download inesperado")
    pasta = Path(tempfile.mkdtemp(prefix="AutoCOR-atualizacao-"))
    destino = pasta / ARQUIVO
    req = urllib.request.Request(release.url_zip, headers={"User-Agent": CABECALHOS["User-Agent"]})
    with urllib.request.urlopen(req, timeout=30) as r, open(destino, "wb") as f:   # noqa: S310
        total = int(r.headers.get("Content-Length") or release.tamanho or 0)
        feito = 0
        while bloco := r.read(1 << 20):
            if cancelado():
                return None
            f.write(bloco)
            feito += len(bloco)
            progresso(feito, total)
    with zipfile.ZipFile(destino) as z:
        z.extractall(pasta)
    exe = pasta / "AutoCOR" / "AutoCOR.exe"
    if not exe.exists():
        raise FileNotFoundError("o pacote baixado não tem o AutoCOR.exe")
    return exe
