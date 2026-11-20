"""Regras de negócio: decide parcelas, forma, valores e bônus de um caso, ou gera pendências."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from .config import Config
from .modelos import Caso, OpcaoPagamento
from .propostas import soma_parcelas_confere

# Q62 — Porto: a proposta às vezes não traz a opção combinada no acordo, mas a Porto sempre calcula assim:
# à vista (1x) em qualquer forma = prêmio −5%; Cartão Porto = −5% em qualquer parcelamento e, à vista, −5% de novo;
# parcelado sem juros = prêmio integral. Com juros não dá para calcular → continua pendência. Só Porto (Tokio não).
PORTO_DESCONTO = Decimal("0.95")
PORTO_SEM_JUROS = {"boleto": 6, "debito": 6, "cartao": 10, "cartao_porto": 12}   # até quantas parcelas sem juros
_CENTAVO = Decimal("0.01")


def _cent(v: Decimal) -> Decimal:
    return v.quantize(_CENTAVO, rounding=ROUND_HALF_UP)


def porto_fora_da_tabela(p, forma: str, parcelas: int) -> OpcaoPagamento | None:
    """Valores da opção que a proposta da Porto não listou, pela regra da Porto (Q62). None = não dá para calcular."""
    if p.seguradora != "PORTO" or p.premio_liquido is None or p.iof is None or p.premio_total is None:
        return None
    if p.premio_total != p.premio_liquido + p.iof:       # custo de apólice: não sei se entra no desconto
        return None
    a_vista = parcelas == 1
    if not a_vista and parcelas > PORTO_SEM_JUROS.get(forma, 0):
        return None                                      # com juros (ou forma que só existe à vista, como PIX)
    if forma == "cartao_porto":
        # base do Cartão Porto: a linha dele na proposta (já com −5%) ou o prêmio geral −5%
        cp = next((o for o in p.opcoes if o.forma == "cartao_porto" and o.parcelas > 1 and o.premio_liquido), None)
        liq, iof = (cp.premio_liquido, cp.iof) if cp else (_cent(p.premio_liquido * PORTO_DESCONTO),
                                                          _cent(p.iof * PORTO_DESCONTO))
        if a_vista:
            liq, iof = _cent(liq * PORTO_DESCONTO), _cent(iof * PORTO_DESCONTO)
        regra = "Cartão Porto à vista = −5% −5%" if a_vista else "Cartão Porto = −5%"
    elif a_vista:
        # à vista é igual em todas as formas: se a proposta tem outro 1x, usa os valores dele
        av = next((o for o in p.opcoes if o.parcelas == 1 and o.forma != "cartao_porto" and o.premio_liquido), None)
        liq, iof = (av.premio_liquido, av.iof) if av else (_cent(p.premio_liquido * PORTO_DESCONTO),
                                                          _cent(p.iof * PORTO_DESCONTO))
        regra = "à vista = −5%"
    else:
        liq, iof = p.premio_liquido, p.iof
        regra = "parcelado sem juros = prêmio integral"
    total = liq + iof
    demais = _cent(total / parcelas)
    return OpcaoPagamento(forma=forma, parcelas=parcelas, primeira=total - demais * (parcelas - 1), demais=demais,
                          premio_total=total, iof=iof, premio_liquido=liq, calculada=True,
                          descricao=f"{parcelas}x {forma} (calculado: {regra})")

# forma falada pelo cliente → formas aceitas na tabela da proposta
_COMPATIVEIS = {
    "boleto": {"boleto"},
    "cartao": {"cartao"},
    "cartao_porto": {"cartao_porto"},
    "pix": {"debito_pix"},
    "debito": {"debito_pix", "debito"},
}


def onde_pendencia(texto: str) -> set[str]:
    """Em qual PDF o consultor resolve a pendência: {"acordo"}, {"proposta"}, os dois ou nenhum (Q63).
    Ex.: “10x boleto não está na tabela de pagamento da proposta” → os dois (o combinado × a tabela)."""
    t = texto.lower()
    onde = set()
    if "acordo" in t:
        onde.add("acordo")
    if "proposta" in t or t.startswith(("prêmio líquido", "comissão", "duas coberturas")):
        onde.add("proposta")
    if "tabela de pagamento" in t:
        onde |= {"acordo", "proposta"}
    return onde


def aplicar(caso: Caso, cfg: Config) -> Caso:
    p, e = caso.proposta, caso.escolha
    if p is None or e is None:
        return caso

    for prob in p.problemas:
        caso.pendencias.append(f"Proposta: {prob}")

    # vigência vem da configuração (Q37); Porto com início diferente → pendência (Q44)
    if p.vigencia_inicio and p.vigencia_inicio != cfg.vigencia_inicio:
        if caso.vigencia_confirmada == p.vigencia_inicio:   # Q64: o consultor confirmou seguir com a padrão
            caso.avisos.append(f"Vigência da proposta começa em {p.vigencia_inicio}; o consultor confirmou cadastrar "
                               f"com a vigência padrão ({cfg.vigencia_inicio} a {cfg.vigencia_fim})")
        else:
            caso.pendencias.append(f"Vigência da proposta começa em {p.vigencia_inicio}, "
                                   f"mas a configuração usa {cfg.vigencia_inicio}")

    # parcelas
    if e.ambigua:
        caso.pendencias.append(f"Parcelas ambíguas no acordo: “{e.trecho_parcelas}” — perguntar ao consultor")
    elif e.parcelas is None:
        caso.pendencias.append("Parcelas não combinadas no acordo — perguntar ao consultor")
    else:
        caso.parcelas = e.parcelas
        if e.origem == "consultor":
            caso.avisos.append(f"Parcelas informadas pelo consultor no app: {e.parcelas}")
        elif e.origem == "oferta aceita":
            caso.avisos.append(f"Parcelas pela oferta do consultor aceita pelo cliente: “{e.trecho_parcelas}”")

    # forma
    if e.forma is None:
        if e.parcelas is not None:
            caso.pendencias.append("Forma de pagamento não combinada no acordo — perguntar ao consultor")
    else:
        if e.forma_presumida:
            caso.avisos.append("Forma de pagamento não citada no acordo: boleto (padrão)")
        caso.forma = e.forma
        caso.cobranca_id = cfg.cobranca.get(e.forma)
        if caso.cobranca_id is None:
            caso.pendencias.append(f"Forma “{e.forma}” sem mapeamento para o SGCOR")

    # opção existe na proposta?
    opcao: OpcaoPagamento | None = None
    if caso.parcelas and caso.forma:
        aceitas = _COMPATIVEIS.get(caso.forma, {caso.forma})
        candidatas = [o for o in p.opcoes if o.forma in aceitas and o.parcelas == caso.parcelas]
        if not candidatas:
            opcao = porto_fora_da_tabela(p, caso.forma, caso.parcelas)
            if opcao is None:
                caso.pendencias.append(
                    f"{caso.parcelas}x {caso.forma} não está na tabela de pagamento da proposta")
            else:
                caso.avisos.append(f"{caso.parcelas}x {caso.forma} não está na tabela da proposta; valores pela regra "
                                   f"da Porto — {opcao.descricao}: total {opcao.premio_total}, IOF {opcao.iof}, "
                                   f"líquido {opcao.premio_liquido} (pode diferir 1 centavo do SGCOR)")
        else:
            opcao = candidatas[0]
            if not soma_parcelas_confere(opcao):
                caso.avisos.append(f"Parcelas de “{opcao.descricao}” não somam o prêmio total")

    # valores: sempre os da forma escolhida (a Porto muda total/IOF/líquido por forma)
    if opcao is not None:
        caso.premio_liquido, caso.iof, caso.premio_total = opcao.premio_liquido, opcao.iof, opcao.premio_total
        if caso.premio_liquido is None:
            caso.pendencias.append(f"Prêmio líquido de “{opcao.descricao}” difere do Resumo do Prêmio (juros?) — conferir")
        elif opcao.premio_total != p.premio_total and not opcao.calculada:
            caso.avisos.append(f"Valores da forma escolhida diferem do demonstrativo geral "
                               f"(total {opcao.premio_total} × {p.premio_total}) — usados os da forma")

    # comissão → bônus
    if p.comissao is not None:
        caso.bonus = cfg.bonus_para(p.comissao)
        if caso.bonus is None:
            caso.pendencias.append(f"Comissão {p.comissao}% fora da tabela de bônus")

    marcada = next((o for o in p.opcoes if o.marcada), None)
    if marcada and caso.parcelas and marcada.parcelas != caso.parcelas:
        caso.avisos.append(f"Acordo ({caso.parcelas}x) diverge da marcação (X) da proposta ({marcada.descricao}) — vale o acordo")
    return caso
