import pytest

from sgcor_renov.atualizacao import Release, baixar, tem_nova, versao_tupla


def test_compara_versoes():
    assert versao_tupla("v1.10.0") > versao_tupla("1.9.3")
    r = Release("1.1.0", "https://github.com/x/y/releases/download/v1.1.0/AutoCOR.zip", 0, "")
    assert tem_nova("1.0.0", r)
    assert not tem_nova("1.1.0", r)
    assert not tem_nova("1.2.0", r)
    assert not tem_nova("1.0.0", None)


def test_so_baixa_do_github():
    with pytest.raises(ValueError):
        baixar(Release("9.9.9", "https://exemplo.com/AutoCOR.zip", 0, ""), lambda *_: None, lambda: False)
