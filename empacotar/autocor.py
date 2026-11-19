"""Ponto de entrada do AutoCOR.exe (PyInstaller)."""
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()   # antes de tudo: os processos da leitura paralela passam por aqui
    from sgcor_renov.ui.janela import main
    sys.exit(main())
