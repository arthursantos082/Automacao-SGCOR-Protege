"""Q92: caminhos longos no Windows.

O Windows (sem "LongPathsEnabled", o padrão) não abre arquivos cujo caminho passa de 260 caracteres: dá "No such file
or directory" mesmo com o arquivo listado na pasta. No Drive compartilhado o começo já gasta ~110
("G:\\.shortcut-targets-by-id\\<id>\\5. Cadastros SGCOR\\<equipe>\\<consultor>\\…") e, com a razão social no nome da
pasta e de novo no nome do PDF, passa fácil (caso real: 270). Com o prefixo \\\\?\\ o Windows aceita até ~32 mil.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

LIMITE = 240          # um pouco abaixo de 260: pastas têm limite menor (248) e o Windows soma o nome do arquivo
_PREFIXO = "\\\\?\\"


def longo(caminho: Path | str) -> str:
    """O caminho como texto, com o prefixo \\\\?\\ quando é longo (no Windows). Curto ou fora do Windows: igual."""
    s = str(caminho)
    if sys.platform != "win32" or len(s) < LIMITE or s.startswith(_PREFIXO):
        return s
    s = os.path.abspath(s)                      # o prefixo exige caminho completo, com "\" (sem "." nem "..")
    if s.startswith("\\\\"):                    # rede: \\servidor\pasta → \\?\UNC\servidor\pasta
        return _PREFIXO + "UNC\\" + s[2:]
    return _PREFIXO + s


def longo_path(caminho: Path | str) -> Path:
    return Path(longo(caminho))
