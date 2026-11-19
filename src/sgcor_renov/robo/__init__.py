"""Robô do SGCOR (Playwright). Ver docs/f0-mapa-sgcor.md para os seletores."""

# Python 3.15: dentro do app, `concurrent.futures.ThreadPoolExecutor` às vezes continua um objeto "lazy_import"
# não resolvido, e o asyncio do Playwright quebra em run_in_executor ("'lazy_import' object is not callable") —
# afeta print com path=, envio de arquivo etc. Amarramos o nome à classe real antes de qualquer uso.
import concurrent.futures as _cf
from concurrent.futures.thread import ThreadPoolExecutor as _TPE

_cf.ThreadPoolExecutor = _TPE
