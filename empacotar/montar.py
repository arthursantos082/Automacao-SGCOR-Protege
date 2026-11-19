"""Monta dist/AutoCOR/ (AutoCOR.exe + config/ editável) e dist/AutoCOR.zip para a TI instalar.

Uso (na raiz do repositório):  .venv\\Scripts\\python.exe empacotar\\montar.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import PyInstaller.__main__

RAIZ = Path(__file__).resolve().parents[1]
DIST = RAIZ / "dist"
APP = DIST / "AutoCOR"
RECURSOS = RAIZ / "src" / "sgcor_renov" / "ui" / "recursos"


def _extras() -> list[str]:
    """Python 3.15: módulos abi3t (ex.: cryptography._rust, usado pelo pdfminer) carregam python3t.dll, que fica em
    <python>\\abi3t-compat e o PyInstaller não acha sozinho."""
    sep = ";" if sys.platform == "win32" else ":"
    dll = Path(sys.base_prefix) / "abi3t-compat" / "python3t.dll"
    return ["--add-binary", f"{dll}{sep}."] if dll.exists() else []


def main() -> None:
    PyInstaller.__main__.run([*_extras(),
        str(RAIZ / "empacotar" / "autocor.py"),
        "--name", "AutoCOR",
        "--onedir",
        "--windowed",
        "--noconfirm",
        "--clean",
        "--icon", str(RECURSOS / "icone.ico"),
        "--paths", str(RAIZ / "src"),
        "--add-data", f"{RECURSOS}{';' if sys.platform == 'win32' else ':'}sgcor_renov/ui/recursos",
        "--collect-submodules", "sgcor_renov",
        "--distpath", str(DIST),
        "--workpath", str(RAIZ / "build"),
        "--specpath", str(RAIZ / "build"),
    ])
    shutil.copytree(RAIZ / "config", APP / "config", dirs_exist_ok=True)   # editável ao lado do .exe
    shutil.copy2(RAIZ / "empacotar" / "LEIA-ME.txt", APP / "LEIA-ME.txt")
    zipado = shutil.make_archive(str(DIST / "AutoCOR"), "zip", DIST, "AutoCOR")
    print(f"\nPronto: {APP / 'AutoCOR.exe'}\nPacote para a TI: {zipado}")


if __name__ == "__main__":
    main()
