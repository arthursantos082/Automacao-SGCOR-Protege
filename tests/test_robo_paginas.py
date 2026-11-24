import base64
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from sgcor_renov.config import carregar
from sgcor_renov.modelos import Caso, Proposta
from sgcor_renov.robo.paginas import LinhaApolice, campos_primeira_tela, escolher_apolice, ler_lista, url_busca

CFG = carregar()


def _linha_html(pid, apolice, cnpj, ramo, cia, ini, fim, tipo="Renovação", status="Vigente", nome="LOTERICA EXEMPLO",
                nivel="Produção"):
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
 <td><i title="Nível {nivel}"></i></td>
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
    assert (l.proposta_id, l.apolice, l.cnpj, l.companhia, l.inicio, l.fim, l.tipo, l.status, l.nivel) == (
        "57675", "2691184", "11222333000181", "TOKIO MARINE", "31/12/2025", "31/12/2026", "Renovação", "Vigente",
        "Produção")
    assert l.ramo == "EMPRESARIAL LOTÉRICO"


def test_ler_lista_nivel_revisao():
    html = _pagina(_linha_html("56035", "2691162", "11.222.333/0001-81", "EMPRESARIAL LOTÉRICO", "TOKIO MARINE",
                               "31/12/2025", "31/12/2026", status="Cancelada", nivel="Revisão"))
    assert ler_lista(html)[0].nivel == "Revisão"


def _l(pid, fim, ini="31/12/2025", cia="TOKIO MARINE", ramo="EMPRESARIAL LOTÉRICO", cnpj="11222333000181",
       status="Vigente", nivel="Produção"):
    return LinhaApolice(pid, "1", "X", cnpj, ramo, cia, ini, fim, "Renovação", status, nivel)


def test_mesma_vigencia_vale_a_de_nivel_producao():
    """Caso real (DDA): duas linhas com vigência final 31/12/2026; a de Nível Revisão (bolinha amarela) não conta."""
    linhas = [_l("56042", "31/12/2026"), _l("56035", "31/12/2026", status="Cancelada", nivel="Revisão")]
    linha, motivo = escolher_apolice(linhas, _caso(), CFG)
    assert motivo is None and linha.proposta_id == "56042"


def test_apolice_que_nao_termina_no_inicio_da_nova_vigencia_vira_pendencia():
    """Caso real (DDA): sem a linha de 2025–2026 em Produção, a mais recente era 2024–2025 — não pode renovar essa."""
    linha, motivo = escolher_apolice([_l("47850", "31/12/2025", ini="31/12/2024"),
                                      _l("56035", "31/12/2026", nivel="Revisão")], _caso(), CFG)
    assert linha is None and "termina em 31/12/2025" in motivo


def test_so_revisao_vira_pendencia():
    linha, motivo = escolher_apolice([_l("56035", "31/12/2026", nivel="Revisão")], _caso(), CFG)
    assert linha is None and "Produção" in motivo


def test_escolhe_a_de_vigencia_mais_recente_da_seguradora_e_ramo():
    linhas = [_l("1", "31/12/2025", ini="31/12/2024"), _l("2", "31/12/2026"),
              _l("3", "30/10/2027", ini="30/10/2026", ramo="VIDA EMPRESARIAL"),
              _l("4", "31/12/2027", ini="31/12/2026", cia="PORTO SEGURO CIA"),
              _l("5", "31/12/2026", nivel="Revisão")]
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
        "Forma de Cobrança": "1", "Parcelas": "6", "1ª Parcela – Vencimento": "15/01/2027", "Emitida": "18/11/2026",
    }


def test_vencimento_da_primeira_parcela_por_seguradora():
    """Q90: Porto 11/01/2027, Tokio 15/01/2027 — também com a config antiga (só "primeira_parcela"), que a
    atualização mantém na máquina."""
    venc = lambda caso, cfg: {c.rotulo: c.valor for c in campos_primeira_tela(caso, cfg)}["1ª Parcela – Vencimento"]
    assert venc(_caso("PORTO"), CFG) == "11/01/2027"
    assert venc(_caso("TOKIO"), CFG) == "15/01/2027"
    import dataclasses
    antiga = dataclasses.replace(CFG, primeira_parcela=None)
    assert (venc(_caso("PORTO"), antiga), venc(_caso("TOKIO"), antiga)) == ("11/01/2027", "15/01/2027")


def test_config_antiga_com_vencimento_unico_usa_o_novo(tmp_path):
    from sgcor_renov.config import PADRAO, carregar as carregar_de
    txt = PADRAO.read_text("utf-8")
    txt = txt.replace('primeira_parcela_porto = "11/01/2027"', 'primeira_parcela = "10/01/2027"')
    txt = txt.replace('primeira_parcela_tokio = "15/01/2027"', '')
    assert 'primeira_parcela = "10/01/2027"' in txt
    (tmp_path / "padrao.toml").write_text(txt, "utf-8")
    cfg = carregar_de(tmp_path / "padrao.toml")
    assert (cfg.primeira_parcela_de("PORTO"), cfg.primeira_parcela_de("TOKIO")) == ("11/01/2027", "15/01/2027")


# ---- Q71: apólice anterior em outro ramo (ex.: CCA em EMPRESARIAL CAIXA AQUI) ou de outra seguradora

def test_outros_ramos_acha_a_vigente_no_caixa_aqui():
    # caso real (WALDINAR): lotérico só tem 2024; a vigente 2025–2026 está no ramo Caixa Aqui
    from sgcor_renov.robo.paginas import vale_procurar_em_outros_ramos
    lot = [_l("44066", "31/12/2024", ini="02/02/2024")]
    linha, motivo = escolher_apolice(lot, _caso(), CFG)
    assert linha is None and vale_procurar_em_outros_ramos(motivo)
    largas = lot + [_l("56224", "31/12/2026", ramo="EMPRESARIAL CAIXA AQUI"),
                    _l("9860", "30/05/2020", ini="30/05/2019", cia="PORTO SEGURO CIA", ramo=""),
                    _l("7", "31/12/2026", ramo="AUTOMÓVEL")]                       # ramo fora da lista: ignora
    linha, motivo = escolher_apolice(largas, _caso(), CFG, outros_ramos=True)
    assert motivo is None and linha.proposta_id == "56224"


def test_outros_ramos_nao_vale_para_ja_cadastrada_nem_empate():
    from sgcor_renov.robo.paginas import vale_procurar_em_outros_ramos
    assert not vale_procurar_em_outros_ramos(escolher_apolice(
        [_l("2", "31/12/2026"), _l("9", "31/12/2027", ini="31/12/2026")], _caso(), CFG)[1])        # Q30
    assert not vale_procurar_em_outros_ramos(escolher_apolice(
        [_l("1", "31/12/2026"), _l("2", "31/12/2026")], _caso(), CFG)[1])                          # empate
    assert vale_procurar_em_outros_ramos(escolher_apolice([], _caso(), CFG)[1])                    # nenhuma


def test_outros_ramos_acha_de_outra_seguradora():
    # a busca larga aceita outra companhia; o robô é que para antes de gravar (troca de seguradora não mapeada)
    linha, motivo = escolher_apolice([_l("5", "31/12/2026", cia="PORTO SEGURO CIA")], _caso(), CFG, outros_ramos=True)
    assert motivo is None and linha.companhia.startswith("PORTO")


def test_ramo_da_tela():
    from sgcor_renov.robo.paginas import ramo_da_tela
    html = ('<table><tr><th>Apólice</th><th>Segurado</th><th>Vigência</th><th>Companhia</th>'
            '<th colspan="2">Classif. / Ramo</th><th>Forma Pagamento</th><th>Nível</th></tr>'
            '<tr><td>2692424</td><td>LOTERICA X</td><td>31/12/2025 à 31/12/2026</td>'
            '<td><span> EMPRESARIAL CAIXA AQUI </span></td><td>BOLETO</td></tr></table>')
    assert ramo_da_tela(html) == "EMPRESARIAL CAIXA AQUI"
    assert ramo_da_tela("<html>sem cabeçalho</html>") is None


def test_plano_inclusoes_usa_incendio_padrao_e_gerpa():
    from decimal import Decimal as D
    from sgcor_renov.config import INCLUIR_PADRAO
    from sgcor_renov.coberturas import Cobertura, Dicionario
    from sgcor_renov.robo.paginas import CoberturaSgcor, linhas_para_incluir, plano_inclusoes
    dic = Dicionario.carregar()
    tabela_html = "".join(f'<input type="hidden" name="dados[{i}][nomeCobertura]" id="" value="{n}">' for i, n in [
        ("602", "GERPA - SUB. DE VALORES FORA DO ESTABELECIMENTO"), ("603", "GERPA - SUB. DE VALORES NO INTERIOR DO ESTABELECIMENTO"),
        ("461", "GERPA - SUB. DE VALORES FORA DO ESTABELECIMENTO"), ("251", "INCÊNDIO"),
        ("582", "INCÊNDIO, RAIO, EXPLOSÃO, IMPLOSÃO E FUMAÇA"), ("798", "VALORES NO INTERIOR DO ESTABELECIMENTO")])
    tabela = linhas_para_incluir(tabela_html)
    assert list(tabela) == ["602", "603", "461", "251", "582", "798"]
    proposta = [(Cobertura("Incêndio, Raio, Explosão, Implosão E Fumaça", D("80000")), "incendio"),
                (Cobertura("Valores No Interior Do Estabelecimento - Caixa Aqui", D("40000")), "valores_interior"),
                (Cobertura("Valores Em Trânsito - Lotérica", D("10000")), "valores_transito"),
                (Cobertura("Danos Elétricos", D("10000")), "danos_eletricos")]          # fora dos 3: não inclui
    sgcor = [CoberturaSgcor("INCÊNDIO, RAIO, EXPLOSÃO, IMPLOSÃO E FUMAÇA", D("60000"), "x")]   # incêndio já existe
    inc, pend = plano_inclusoes(proposta, sgcor, dic, ("incendio", "valores_interior", "valores_transito"),
                                INCLUIR_PADRAO, tabela)
    assert pend == []
    assert [(i.cobertura_id, i.lmi) for i in inc] == [("603", D("40000")), ("602", D("10000"))]   # GERPA; 1ª linha
    # sem a linha padrão na tabela → pendência (não chuta uma parecida)
    inc, pend = plano_inclusoes(proposta, sgcor, dic, ("incendio", "valores_interior"), INCLUIR_PADRAO,
                                {"251": "INCÊNDIO"})
    assert inc == [] and len(pend) == 1 and "GERPA - SUB. DE VALORES NO INTERIOR" in pend[0]


# ---- Q73: CCA (Caixa Aqui) x lotérica — incluir coberturas só quando o ramo mudou de verdade

def test_produto_da_proposta_cca_ou_loterica():
    from amostras import PORTO, TOKIO
    from sgcor_renov.propostas import ler_porto, ler_tokio, produto
    assert ler_porto(PORTO).produto == "loterico" and ler_tokio(TOKIO).produto == "loterico"
    assert produto("Valores No Interior Do Estabelecimento - Caixa Aqui") == "caixa_aqui"     # Tokio (WALDINAR)
    assert produto("SEGURO EMPRESA - CCA - CORRESPONDENTE") == "caixa_aqui"                    # Porto (R J R)
    assert produto("ACCAO LOTÉRICA") == "loterico"                                              # "CCA" só palavra inteira


def test_mudou_de_ramo():
    from sgcor_renov.modelos import Proposta
    from sgcor_renov.robo.paginas import mudou_de_ramo
    cca, lot = _caso(), _caso()
    cca.proposta, lot.proposta = Proposta("TOKIO", produto="caixa_aqui"), Proposta("TOKIO", produto="loterico")
    assert not mudou_de_ramo("EMPRESARIAL CAIXA AQUI", cca)        # WALDINAR: CCA renovando em Caixa Aqui = normal
    assert mudou_de_ramo("EMPRESARIAL LOTÉRICO", cca)
    assert mudou_de_ramo("EMPRESARIAL CAIXA AQUI", lot)            # lotérica vinda de um Caixa Aqui → inclui
    assert not mudou_de_ramo("EMPRESARIAL LOTÉRICO", lot)
    assert not mudou_de_ramo(None, lot) and not mudou_de_ramo("", cca)


# ---- Q83: vigência alterada pelo consultor

def test_vigencia_alterada_vai_para_a_primeira_tela_e_para_a_busca():
    c = _caso()
    c.vigencia_alterada = ("05/12/2026", "05/12/2027")
    campos = {x.rotulo: x.valor for x in campos_primeira_tela(c, CFG, hoje=date(2026, 11, 23))}
    assert (campos["Vigência início"], campos["Vigência fim"]) == ("05/12/2026", "05/12/2027")
    # a apólice a renovar é a que termina no início NOVO (05/12/2026), não no da configuração
    linha, motivo = escolher_apolice([_l("7", "05/12/2026", ini="05/12/2025")], c, CFG)
    assert motivo is None and linha.proposta_id == "7"
    linha, motivo = escolher_apolice([_l("8", "31/12/2026")], c, CFG)
    assert linha is None and "não em 05/12/2026" in motivo
    # sem alteração continua a da configuração
    assert escolher_apolice([_l("8", "31/12/2026")], _caso(), CFG)[1] is None


def test_empate_na_vigencia_desempata_pelo_numero_da_apolice_da_proposta():
    """Q94 (caso real JOSE GONCALVES DANTAS): duas apólices em Produção terminando em 31/12/2026; a proposta diz
    "renova a apólice 2696649" e só uma delas tem esse número → é ela."""
    from dataclasses import replace
    caso = _caso()
    caso.proposta.apolice_anterior = "2696649"
    a = replace(_l("65712", "31/12/2026", ini="26/06/2026"), apolice="2696649", tipo="Nova")
    b = replace(_l("63305", "31/12/2026"), apolice="2688645", status="?")
    linha, motivo = escolher_apolice([b, a], caso, CFG)
    assert motivo is None and linha.proposta_id == "65712"
    # nenhuma (ou as duas) com o número da proposta → continua pendência, como antes
    caso.proposta.apolice_anterior = "9999999"
    assert escolher_apolice([b, a], caso, CFG)[1].startswith("Mais de uma")
    caso.proposta.apolice_anterior = "2696649"
    assert escolher_apolice([replace(b, apolice="2696649"), a], caso, CFG)[1].startswith("Mais de uma")
    # nº provisório (123456) não desempata: muitas têm
    caso.proposta.apolice_anterior = "123456"
    assert escolher_apolice([replace(b, apolice="123456"), a], caso, CFG)[1].startswith("Mais de uma")


def test_ramo_sem_endereco_no_tooltip_e_lido_e_o_endosso_cca_e_renovado():
    """Q96 (caso real L M CARNAUBA, CCA Porto): o tooltip vinha "Ramo: EMPRESARIAL CAIXA AQUI, 1 - LOCAL …\nBairro:
    …" (sem "Endereço:"); o ramo saía vazio, a linha era descartada e virava "Nenhuma apólice … em nenhuma
    seguradora". A renovável é o endosso (a original fica "endossada", sem o botão Renovar)."""
    linha = _linha_html("65869", "4069103", "15.328.700/0001-87", "X", "PORTO SEGURO CIA. DE SEGUROS GERAIS",
                        "31/12/2025", "31/12/2026", tipo="Endosso")
    linha = linha.replace('title="Ramo: X Endereço: RUA X"',
                          'title="Ramo: EMPRESARIAL CAIXA AQUI, 1 - LOCAL ESCRITORIOS DEMAIS-TER\nBairro: CENTRO\n'
                          'Cidade: ADOS"')
    [l] = ler_lista(_pagina(linha))
    assert l.ramo.startswith("EMPRESARIAL CAIXA AQUI") and "Bairro" not in l.ramo
    caso = _caso("PORTO", cnpj="15328700000187")
    caso.proposta.produto = "caixa_aqui"
    escolhida, motivo = escolher_apolice([l], caso, CFG, outros_ramos=True)
    assert motivo is None and escolhida.proposta_id == "65869"
    # o formato de sempre continua igual
    [n] = ler_lista(_pagina(_linha_html("1", "2", "11.222.333/0001-81", "EMPRESARIAL LOTÉRICO", "TOKIO MARINE",
                                        "31/12/2025", "31/12/2026")))
    assert n.ramo == "EMPRESARIAL LOTÉRICO"


def test_endosso_em_revisao_e_renovado_quando_e_a_ultima_opcao():
    """Q97 (caso real ESTRELA DA SORTE): só o endosso em Revisão tem o botão Renovar (os outros ficam cinza e nem
    entram na lista lida) e é a apólice que a proposta diz renovar → renova ele. Fora disso, Revisão continua
    desconsiderada (Q54)."""
    from dataclasses import replace
    caso = _caso()
    caso.proposta.apolice_anterior = "2693657"
    endosso = replace(_l("64310", "31/12/2026", ini="17/01/2026", nivel="Revisão"), apolice="2693657", tipo="Endosso")
    linha, motivo = escolher_apolice([endosso], caso, CFG)
    assert motivo is None and linha.proposta_id == "64310"
    so_revisao = "Nenhuma apólice em Nível Produção"
    # nº diferente do da proposta, ou não é endosso → continua pendência
    assert escolher_apolice([replace(endosso, apolice="1")], caso, CFG)[1].startswith(so_revisao)
    assert escolher_apolice([replace(endosso, tipo="Renovação")], caso, CFG)[1].startswith(so_revisao)
    # não é a última opção (há outra renovável em Revisão) → pendência
    outra = replace(endosso, proposta_id="64311", apolice="2693658")
    assert escolher_apolice([endosso, outra], caso, CFG)[1].startswith(so_revisao)
    # nº provisório não serve para identificar
    caso.proposta.apolice_anterior = "123456"
    assert escolher_apolice([replace(endosso, apolice="123456")], caso, CFG)[1].startswith(so_revisao)
    # com uma em Produção, a regra de sempre (a de Produção)
    caso.proposta.apolice_anterior = "2693657"
    producao = replace(_l("1", "31/12/2026"), apolice="999")
    assert escolher_apolice([endosso, producao], caso, CFG)[0].proposta_id == "1"
