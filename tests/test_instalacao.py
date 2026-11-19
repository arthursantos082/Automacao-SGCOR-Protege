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
