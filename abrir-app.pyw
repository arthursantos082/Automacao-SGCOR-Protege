"""Abre o AutoCOR sem janela de console (alvo do atalho da área de trabalho; o .exe vem na F4)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

if __name__ == "__main__":   # obrigatório: os processos da leitura paralela reimportam este arquivo
    from sgcor_renov.ui.janela import main
    sys.exit(main())
