import sys

from .janela import main

if __name__ == "__main__":   # obrigatório: os processos da leitura paralela reimportam este módulo
    sys.exit(main())
