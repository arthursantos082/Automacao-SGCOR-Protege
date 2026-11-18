"""Regras de negócio: decide parcelas, forma, valores e bônus de um caso, ou gera pendências."""
from __future__ import annotations

from .config import Config
from .modelos import Caso, OpcaoPagamento
from .propostas import soma_parcelas_confere

# forma falada pelo cliente → formas aceitas na tabela da proposta
_COMPATIVEIS = {
    "boleto": {"boleto"},
    "cartao": {"cartao"},
    "cartao_porto": {"cartao_porto"},
    "pix": {"debito_pix"},
    "debito": {"debito_pix", "debito"},
}


def aplicar(caso: Caso, cfg: Config) -> Caso:
    p, e = caso.proposta, caso.escolha
    if p is None or e is None:
        return caso

    for prob in p.problemas:
        caso.pendencias.append(f"Proposta: {prob}")

    # parcelas
    if e.ambigua:
        caso.pendencias.append(f"Parcelas ambíguas no acordo: “{e.trecho_parcelas}” — perguntar ao consultor")
    elif e.parcelas is None:
        caso.pendencias.append("Parcelas não combinadas no acordo — perguntar ao consultor")
    else:
        caso.parcelas = e.parcelas
        if e.origem == "oferta aceita":
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
            caso.pendencias.append(
                f"{caso.parcelas}x {caso.forma} não está na tabela de pagamento da proposta")
        else:
            opcao = candidatas[0]
            if not soma_parcelas_confere(opcao):
                caso.avisos.append(f"Parcelas de “{opcao.descricao}” não somam o prêmio total")

    # valores: sempre os da forma escolhida (a Porto muda total/IOF/líquido por forma)
    if opcao is not None:
        caso.premio_liquido, caso.iof, caso.premio_total = opcao.premio_liquido, opcao.iof, opcao.premio_total
        if caso.premio_liquido is None:
            caso.pendencias.append(f"Prêmio líquido de “{opcao.descricao}” difere do Resumo do Prêmio (juros?) — conferir")
        elif opcao.premio_total != p.premio_total:
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
