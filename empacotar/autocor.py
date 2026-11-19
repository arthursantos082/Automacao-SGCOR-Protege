"""Ponto de entrada do AutoCOR.exe (PyInstaller)."""
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()   # antes de tudo: os processos da leitura paralela passam por aqui
    from sgcor_renov.instalacao import tratar
    if tratar(sys.argv[1:]):           # instalar/desinstalar (o .exe se instala em Program Files)
        sys.exit(0)
    from sgcor_renov.ui.janela import main
    sys.exit(main())
