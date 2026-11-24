from sgcor_renov.instalacao import copiar_programa, instalado_em, tratar


def _programa(raiz, versao):
    (raiz / "_internal").mkdir(parents=True)
    (raiz / "_internal" / f"lib-{versao}.dll").write_text(versao)
    (raiz / "config").mkdir()
    (raiz / "config" / "padrao.toml").write_text(f"versao = '{versao}'")
    (raiz / "AutoCOR.exe").write_text(versao)
    return raiz


def test_primeira_instalacao_e_atualizacao_preservam_config(tmp_path):
    destino = tmp_path / "Program Files" / "AutoCOR"
    copiar_programa(_programa(tmp_path / "v1", "v1"), destino)
    assert (destino / "AutoCOR.exe").read_text() == "v1"
    assert not (destino / "config.novo").exists()

    (destino / "config" / "padrao.toml").write_text("ajustado pela TI")
    copiar_programa(_programa(tmp_path / "v2", "v2"), destino)
    assert (destino / "AutoCOR.exe").read_text() == "v2"
    assert [p.name for p in (destino / "_internal").iterdir()] == ["lib-v2.dll"]      # _internal antiga sai
    assert (destino / "config" / "padrao.toml").read_text() == "ajustado pela TI"     # da TI fica
    assert (destino / "config.novo" / "padrao.toml").read_text() == "versao = 'v2'"   # nova para comparar


def test_instalado_em_e_fora_do_exe(tmp_path):
    assert instalado_em(tmp_path, tmp_path / "." )
    assert not instalado_em(tmp_path / "a", tmp_path / "b")
    assert tratar(["--instalar"]) is False   # rodando pelo Python (não é o .exe): nunca instala


# ---- Q79: atualização tudo ou nada (arquivo em uso não pode deixar a instalação pela metade)

def test_arquivo_em_uso_nao_apaga_nada(tmp_path, monkeypatch):
    import time
    import pytest
    from sgcor_renov.instalacao import ArquivoEmUso
    monkeypatch.setattr(time, "sleep", lambda s: None)
    destino = tmp_path / "Program Files" / "AutoCOR"
    copiar_programa(_programa(tmp_path / "v1", "v1"), destino)
    for nome in ("charset_normalizer.pyd", "cryptography_rust.pyd"):       # como no caso real
        (destino / "_internal" / nome).write_text("v1")
    preso = open(destino / "_internal" / "cryptography_rust.pyd")             # "em uso" (o Windows não renomeia)
    try:
        with pytest.raises(ArquivoEmUso):
            copiar_programa(_programa(tmp_path / "v2", "v2"), destino)
    finally:
        preso.close()
    # nada foi apagado: a versão instalada continua inteira
    assert sorted(p.name for p in (destino / "_internal").iterdir()) == [
        "charset_normalizer.pyd", "cryptography_rust.pyd", "lib-v1.dll"]
    assert (destino / "AutoCOR.exe").read_text() == "v1"
    # depois de fechar, a atualização passa e não sobra a pasta antiga
    copiar_programa(_programa(tmp_path / "v2b", "v2"), destino)
    assert [p.name for p in (destino / "_internal").iterdir()] == ["lib-v2.dll"]
    assert not (destino / "_internal.antigo").exists()


def test_falha_no_meio_da_copia_volta_a_versao_anterior(tmp_path, monkeypatch):
    import shutil
    from pathlib import Path
    import pytest
    from sgcor_renov.instalacao import ArquivoEmUso
    destino = tmp_path / "Program Files" / "AutoCOR"
    copiar_programa(_programa(tmp_path / "v1", "v1"), destino)
    copy2 = shutil.copy2

    def falha_no_exe(origem, alvo, *a, **k):
        if Path(origem).name == "AutoCOR.exe":
            raise PermissionError("AutoCOR.exe em uso")
        return copy2(origem, alvo, *a, **k)

    monkeypatch.setattr(shutil, "copy2", falha_no_exe)
    with pytest.raises(ArquivoEmUso):
        copiar_programa(_programa(tmp_path / "v2", "v2"), destino)
    assert [p.name for p in (destino / "_internal").iterdir()] == ["lib-v1.dll"]      # voltou a anterior
    assert not (destino / "_internal.antigo").exists()


# ---- Q82: anexo lido pelo AutoCOR (pasta do Google Drive): tenta de novo enquanto o Drive baixa

def test_ler_arquivo_espera_o_drive(tmp_path, monkeypatch):
    import time
    from pathlib import Path
    import pytest
    from sgcor_renov.robo.navegador import FalhaRobo, ler_arquivo
    monkeypatch.setattr(time, "sleep", lambda s: None)
    arq = tmp_path / "ACORDO X.pdf"
    arq.write_bytes(b"%PDF-1.4 conteudo")
    leituras = iter([OSError("O provedor de arquivos de nuvem não está em execução"), b"", b"%PDF-1.4 conteudo"])
    original = Path.read_bytes

    def lendo(self):
        if self == arq:
            r = next(leituras)
            if isinstance(r, Exception):
                raise r
            return r
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", lendo)
    assert ler_arquivo(arq) == b"%PDF-1.4 conteudo"          # 1ª: erro do Drive; 2ª: vazio; 3ª: ok
    monkeypatch.setattr(Path, "read_bytes", lambda self: (_ for _ in ()).throw(OSError("sem rede")))
    with pytest.raises(FalhaRobo, match="ACORDO X.pdf"):
        ler_arquivo(arq, tentativas=2)
