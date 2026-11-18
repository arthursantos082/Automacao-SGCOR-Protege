import base64
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from sgcor_renov.config import carregar
from sgcor_renov.modelos import Caso, Proposta
from sgcor_renov.robo.paginas import LinhaApolice, campos_primeira_tela, escolher_apolice, ler_lista, url_busca

CFG = carregar()


def _linha_html(pid, apolice, cnpj, ramo, cia, ini, fim, tipo="Renovação", status="Vigente", nome="LOTERICA EXEMPLO"):
    """Imita uma linha de table#tabled_grid do SGCOR (estrutura de 18/11/2026)."""
    return f"""
<tr class="linhaHover">
 <td><i title="Visualizar" onclick="abrirJanela2('popup.php?op=propostasVisualizar&propostaId={pid}')"></i></td>
 <td><i title="Renovar" onclick="window.location='?op=propostas&form=alterar&propostaId={pid}&renovar=true';"></i></td>
 <td>{pid}</td>
 <td title="Pesquisar pela apólice Apólice: {apolice} Proposta: 1">{apolice}</td>
 <td title="Tipo: Segurado Nome: {nome} CPF/CNPJ: {cnpj}">{nome}</td>
 <td><i title="Ramo: {ramo} Endereço: RUA X"></i></td>
 <td><img title="{cia}"></td>
 <td>{ini}</td><td>{fim}</td>
 <td><i title="{tipo} ID: 1"></i></td>
 <td><i title="{status}"></i></td>
</tr>"""


def _pagina(*linhas):
    return f'<table id="tabled_grid"><tr><th>Opções</th></tr>{"".join(linhas)}</table>'


def _caso(seg="TOKIO", cnpj="11222333000181"):
    p = Proposta(seguradora=seg, numero="15800001", cnpj=cnpj, comissao=21)
    return Caso(seguradora=seg, pasta=Path("."), nome="LOTERICA EXEMPLO", proposta=p, parcelas=6, forma="boleto",
                cobranca_id=1, premio_total=D("1073.80"), iof=D("73.80"), premio_liquido=D("1000.00"))


def test_url_busca_leva_o_formulario_em_base64():
    url = url_busca(CFG, "11222333000181", "PORTO")
    p = parse_qs(base64.b64decode(parse_qs(urlparse(url).query)["p"][0]).decode())
    assert p == {"cpf_cnpj": ["11.222.333/0001-81"], "tipoCpfCnpj": ["segurado"], "companhiaId": ["12"], "ramoId": ["9"]}
    assert "companhiaId=13" in base64.b64decode(parse_qs(urlparse(url_busca(CFG, "1", "TOKIO")).query)["p"][0]).decode()


def test_ler_lista():
    html = _pagina(_linha_html("57675", "2691184", "11.222.333/0001-81", "EMPRESARIAL LOTÉRICO", "TOKIO MARINE",
                               "31/12/2025", "31/12/2026"))
    [l] = ler_lista(html)
    assert (l.proposta_id, l.apolice, l.cnpj, l.companhia, l.inicio, l.fim, l.tipo, l.status) == (
        "57675", "2691184", "11222333000181", "TOKIO MARINE", "31/12/2025", "31/12/2026", "Renovação", "Vigente")
    assert l.ramo == "EMPRESARIAL LOTÉRICO"


def _l(pid, fim, ini="31/12/2025", cia="TOKIO MARINE", ramo="EMPRESARIAL LOTÉRICO", cnpj="11222333000181",
       status="Vigente"):
    return LinhaApolice(pid, "1", "X", cnpj, ramo, cia, ini, fim, "Renovação", status)


def test_escolhe_a_de_vigencia_mais_recente_da_seguradora_e_ramo():
    linhas = [_l("1", "31/12/2025", ini="31/12/2024"), _l("2", "31/12/2026"),
              _l("3", "30/10/2027", ini="30/10/2026", ramo="VIDA EMPRESARIAL"),
              _l("4", "31/12/2027", ini="31/12/2026", cia="PORTO SEGURO CIA")]
    linha, motivo = escolher_apolice(linhas, _caso(), CFG)
    assert motivo is None and linha.proposta_id == "2"


def test_renovacao_ja_cadastrada_vira_pendencia():
    linha, motivo = escolher_apolice([_l("2", "31/12/2026"), _l("9", "31/12/2027", ini="31/12/2026")], _caso(), CFG)
    assert linha is None and "já cadastrada" in motivo


def test_empate_e_nenhuma_viram_pendencia():
    assert escolher_apolice([_l("1", "31/12/2026"), _l("2", "31/12/2026")], _caso(), CFG)[1].startswith("Mais de uma")
    assert escolher_apolice([], _caso(), CFG)[1].startswith("Nenhuma")
    assert escolher_apolice([_l("1", "31/12/2026", cnpj="99")], _caso(), CFG)[1].startswith("Nenhuma")


def test_campos_da_primeira_tela_sao_os_do_consultor():
    campos = campos_primeira_tela(_caso(), CFG, hoje=date(2026, 11, 18))
    v = {c.rotulo: c.valor for c in campos}
    assert v == {
        "Proposta": "15800001", "Apólice": "123456", "Apólice (Baixa comissão)": "123456",
        "Vigência início": "31/12/2026", "Vigência fim": "31/12/2027", "Confirma as datas de vigência?": "sim",
        "Comissão": "21,00", "Prêmio Total": "1.073,80", "IOF": "73,80", "Prêmio Líquido": "1.000,00",
        "Forma de Cobrança": "1", "Parcelas": "6", "1ª Parcela – Vencimento": "10/01/2027", "Emitida": "18/11/2026",
    }
