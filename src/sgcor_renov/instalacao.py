"""O AutoCOR.exe se instala sozinho (sem instalador separado: o Controle Inteligente de Aplicativos do Windows 11
bloqueou o AutoCOR-Setup.exe de arquivo único, mas deixa o AutoCOR.exe rodar).

- Aberto fora de C:\\Program Files\\AutoCOR (ex.: da pasta descompactada do .zip), pergunta se quer instalar.
- "Instalar" reabre o próprio .exe como administrador (UAC) com --instalar: copia a pasta para Program Files,
  cria o atalho no Menu Iniciar, PERGUNTA pelo atalho na área de trabalho e registra em "Aplicativos instalados".
- Numa atualização, a pasta config\\ já ajustada pela TI é preservada (a nova vai como config.novo\\).
- --desinstalar (usado pelo Windows em "Aplicativos instalados") remove programa, atalhos e registro; os dados do
  consultor em %LOCALAPPDATA%\\SGCOR-Renovacoes ficam.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path

NOME = "AutoCOR"
VERSAO = "1.1.7"
EDITOR = "Grupo Protege"
CHAVE_UNINSTALL = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{NOME}"
CSIDL_COMMON_DESKTOP, CSIDL_COMMON_PROGRAMS, CSIDL_PROGRAM_FILES = 0x19, 0x17, 0x26


def pasta_especial(csidl: int) -> Path:
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
    return Path(buf.value)


def destino_padrao() -> Path:
    return pasta_especial(CSIDL_PROGRAM_FILES) / NOME


def instalado_em(pasta: Path, destino: Path) -> bool:
    try:
        return pasta.resolve() == destino.resolve()
    except OSError:
        return False


class ArquivoEmUso(Exception):
    """Algum arquivo do AutoCOR instalado está em uso (AutoCOR aberto, antivírus…): nada foi apagado."""


def _renomear(de: Path, para: Path, tentativas: int = 10, espera: float = 1.0) -> None:
    """No Windows, renomear uma pasta falha se algum arquivo dela estiver em uso — e aí NADA muda. Tenta algumas
    vezes (o antivírus costuma soltar o arquivo em segundos)."""
    import time
    for i in range(tentativas):
        try:
            os.replace(de, para)
            return
        except PermissionError as e:
            if i == tentativas - 1:
                raise ArquivoEmUso(str(e)) from e
            time.sleep(espera)


def copiar_programa(origem: Path, destino: Path) -> None:
    """Copia a pasta do programa; troca _internal inteira; preserva config\\ já existente (nova → config.novo).
    Q79: tudo ou nada. Antes apagava _internal no lugar e, se um arquivo estivesse em uso, parava no meio — a
    instalação ficava sem metade dos módulos (caso real: "hazmat/bindings" e depois "charset_normalizer.cd").
    Agora: renomeia a _internal antiga (se algo estiver em uso, o Windows recusa e nada é apagado), copia a nova e só
    no fim apaga a antiga; se a cópia falhar, volta a antiga."""
    destino.mkdir(parents=True, exist_ok=True)
    interno, velho = destino / "_internal", destino / "_internal.antigo"
    shutil.rmtree(velho, ignore_errors=True)            # sobra de uma atualização anterior
    if interno.exists():
        _renomear(interno, velho)
    try:
        for item in origem.iterdir():
            alvo = destino / item.name
            if item.name == "config.novo":
                continue
            if item.name == "config" and alvo.exists():
                shutil.rmtree(destino / "config.novo", ignore_errors=True)
                shutil.copytree(item, destino / "config.novo")
            elif item.is_dir():
                shutil.copytree(item, alvo, dirs_exist_ok=True)
            else:
                shutil.copy2(item, alvo)
    except Exception as e:
        if velho.exists():                              # volta como estava
            shutil.rmtree(interno, ignore_errors=True)
            os.replace(velho, interno)
        if isinstance(e, PermissionError):
            raise ArquivoEmUso(str(e)) from e
        raise
    shutil.rmtree(velho, ignore_errors=True)            # se algo ainda estiver preso, sai na próxima atualização


# ---------------------------------------------------------------- Windows (precisa de administrador)

def _admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def _como_admin(*args: str, exe: str | None = None) -> bool:
    params = " ".join(f'"{a}"' for a in args)
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", exe or sys.executable, params, None, 1) > 32


def abrir_instalador(exe: Path) -> bool:
    """Atualização: abre o AutoCOR.exe novo (baixado) como administrador para se instalar."""
    return _como_admin("--instalar", exe=str(exe))


def versao_instalada() -> str | None:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, CHAVE_UNINSTALL) as k:
            return str(winreg.QueryValueEx(k, "DisplayVersion")[0])
    except OSError:
        return None


def _atalho(lnk: Path, exe: Path) -> None:
    from PySide6.QtCore import QFile
    lnk.unlink(missing_ok=True)
    QFile.link(str(exe), str(lnk))          # .lnk com o ícone do próprio AutoCOR.exe


def _registrar(destino: Path) -> None:
    import winreg
    exe = destino / f"{NOME}.exe"
    tamanho_kb = sum(f.stat().st_size for f in destino.rglob("*") if f.is_file()) // 1024
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, CHAVE_UNINSTALL, 0, winreg.KEY_WRITE) as k:
        for nome, valor in (("DisplayName", NOME), ("DisplayVersion", VERSAO), ("Publisher", EDITOR),
                            ("InstallLocation", str(destino)), ("DisplayIcon", f"{exe},0"),
                            ("UninstallString", f'"{exe}" --desinstalar')):
            winreg.SetValueEx(k, nome, 0, winreg.REG_SZ, valor)
        winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, tamanho_kb)
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)


def _outros_autocor_abertos() -> bool:
    r = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {NOME}.exe", "/NH", "/FO", "CSV"], capture_output=True,
                       text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    return sum(1 for linha in r.stdout.splitlines() if f'"{NOME}.exe"'.lower() in linha.lower()) > 1


# ---------------------------------------------------------------- diálogos

def _app():
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "ui" / "recursos" / "icone.ico")))
    return app


def _pergunta(texto: str, sim: str, nao: str) -> bool:
    from PySide6.QtWidgets import QMessageBox
    _app()
    m = QMessageBox(QMessageBox.Question, NOME, texto)
    b_sim = m.addButton(sim, QMessageBox.AcceptRole)
    m.addButton(nao, QMessageBox.RejectRole)
    m.setDefaultButton(b_sim)
    m.exec()
    return m.clickedButton() is b_sim


def _aviso(texto: str, erro: bool = False) -> None:
    from PySide6.QtWidgets import QMessageBox
    _app()
    (QMessageBox.critical if erro else QMessageBox.information)(None, NOME, texto)


def _esperar_fechar() -> bool:
    import time
    for _ in range(30):                 # na atualização, o app antigo está fechando: dá um tempo antes de pedir
        if not _outros_autocor_abertos():
            return True
        time.sleep(0.5)
    while _outros_autocor_abertos():
        if not _pergunta(f"Feche o {NOME} que está aberto antes de continuar.", "Já fechei", "Cancelar"):
            return False
    return True


def instalar(origem: Path, destino: Path) -> None:
    if not _esperar_fechar():
        return
    while True:
        try:
            copiar_programa(origem, destino)
            break
        except ArquivoEmUso as e:
            if not _pergunta(f"Não deu para atualizar: um arquivo do {NOME} está em uso.\n\nFeche todos os {NOME} "
                             f"abertos (se precisar, pelo Gerenciador de Tarefas) e tente de novo. Nada foi apagado: a "
                             f"versão instalada continua funcionando.\n\nDetalhe: {e}", "Tentar de novo", "Cancelar"):
                return
    exe = destino / f"{NOME}.exe"
    _registrar(destino)
    _atalho(pasta_especial(CSIDL_COMMON_PROGRAMS) / f"{NOME}.lnk", exe)
    extra = ""
    lnk_desktop = pasta_especial(CSIDL_COMMON_DESKTOP) / f"{NOME}.lnk"
    if lnk_desktop.exists():            # atualização: já tem atalho, só renova (não pergunta de novo)
        _atalho(lnk_desktop, exe)
        extra = " e na área de trabalho"
    elif _pergunta(f"Criar um atalho do {NOME} na área de trabalho?", "Criar atalho", "Não"):
        _atalho(lnk_desktop, exe)
        extra = " e na área de trabalho"
    if (destino / "config.novo").exists():
        extra += ("\n\nA configuração que já estava instalada foi mantida (config). A da versão nova ficou em "
                  "config.novo, para comparar.")
    if _pergunta(f"{NOME} {VERSAO} instalado em {destino}.\nAtalho criado no Menu Iniciar{extra}.", f"Abrir o {NOME}",
                 "Fechar"):
        subprocess.Popen(["explorer.exe", str(exe)])   # pelo Explorer: abre como o usuário, sem administrador


def desinstalar(destino: Path) -> None:
    if not _pergunta(f"Remover o {NOME} deste computador?\n\nOs dados do consultor (estado, logs) não são apagados.",
                     "Remover", "Cancelar"):
        return
    if not _esperar_fechar():
        return
    import winreg
    for lnk in (pasta_especial(CSIDL_COMMON_PROGRAMS) / f"{NOME}.lnk",
                pasta_especial(CSIDL_COMMON_DESKTOP) / f"{NOME}.lnk"):
        lnk.unlink(missing_ok=True)
    try:
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, CHAVE_UNINSTALL)
    except OSError:
        pass
    _aviso(f"{NOME} removido.")
    # os arquivos estão em uso por este processo: um cmd apaga a pasta logo depois que ele terminar
    subprocess.Popen(f'cmd /c ping 127.0.0.1 -n 4 > nul & rmdir /s /q "{destino}"',
                     creationflags=subprocess.CREATE_NO_WINDOW, cwd=str(destino.parent))


def tratar(args: list[str]) -> bool:
    """Chamado no início do AutoCOR.exe. True = foi instalação/desinstalação (não abre a janela principal)."""
    if not getattr(sys, "frozen", False) or sys.platform != "win32":
        return False
    pasta = Path(sys.executable).parent
    destino = destino_padrao()
    try:
        if "--instalar" in args:
            if _admin():
                instalar(pasta, destino)
            return True
        if "--desinstalar" in args:
            if not _admin():
                _como_admin("--desinstalar")
            else:
                desinstalar(pasta)
            return True
        if instalado_em(pasta, destino) or "--portatil" in args:
            return False
        atual = versao_instalada() if (destino / f"{NOME}.exe").exists() else None
        if atual:
            texto, botao = (f"O {NOME} {atual} está instalado neste computador.\n\nAtualizar para a versão {VERSAO}?\n"
                            f"(o Windows vai pedir permissão de administrador; a configuração é mantida)", "Atualizar")
        else:
            texto, botao = (f"O {NOME} ainda não está instalado neste computador.\n\nInstalar em {destino}?\n"
                            f"(o Windows vai pedir permissão de administrador)", "Instalar")
        if _pergunta(texto, botao, "Só abrir desta vez"):
            if not _como_admin("--instalar"):
                _aviso("A instalação precisa de permissão de administrador.", erro=True)
            return True
        return False
    except Exception as e:   # noqa: BLE001 — mostra o erro em vez de sumir
        _aviso(f"Erro na instalação:\n{e}", erro=True)
        return True
