"""Classificação dos PDFs e leitura das propostas Porto (orçamento) e Tokio (cotação)."""
from __future__ import annotations

import re
from decimal import Decimal

from .modelos import OpcaoPagamento, Proposta
from .numeros import CNPJ, DINHEIRO, dinheiro, mais_um_ano, so_digitos

CNPJ_TOKIO = "33164021000100"
# Q68: problema que o consultor pode confirmar no app (o robô acha a apólice no SGCOR pelo CNPJ e pela vigência)
SEM_APOLICE_ANTERIOR = "nº da apólice anterior"
CNPJ_PORTO = "61198164000160"


def produto(texto: str) -> str:
    """Q73: CCA (Correspondente Caixa Aqui) ou lotérica. A Tokio escreve "Caixa Aqui" nas coberturas; a Porto,
    "CCA". As propostas de lotérica repetem "Lotérico" (14 a 20 vezes); as de CCA, no máximo 1."""
    t = texto.upper()
    return "caixa_aqui" if "CAIXA AQUI" in t or re.search(r"\bCCA\b", t) else "loterico"


def classificar(texto: str) -> str:
    """ACORDO | ACORDO_EMAIL | PROPOSTA_PORTO | PROPOSTA_TOKIO | DESCONHECIDO (pelo conteúdo, nunca pelo nome)."""
    t = texto.upper()
    if "HISTÓRICO DE ATENDIMENTO" in t or "HISTORICO DE ATENDIMENTO" in t:
        return "ACORDO"
    if "COTAÇÃO DE SEGURO TOKIO MARINE" in t:
        return "PROPOSTA_TOKIO"
    if "PORTO SEGURO" in t and "NÚMERO DO ORÇAMENTO" in t:
        return "PROPOSTA_PORTO"
    if "MAIL.GOOGLE.COM" in t or re.search(r"^E-MAIL DE .+", t, re.M):
        return "ACORDO_EMAIL"
    return "DESCONHECIDO"


# ---------------------------------------------------------------- Tokio

def _plano_para_parcelas(plano: str) -> int:
    plano = plano.strip().upper()
    if plano == "À VISTA" or plano == "A VISTA":
        return 1
    a, b = (int(x) for x in re.split(r"\s*\+\s*", plano))
    return a + b


_FORMA_TOKIO = {"boleto": "boleto", "débito/pix": "debito_pix", "cartão de crédito": "cartao"}

_OPCAO_TOKIO = re.compile(
    rf"^(Boleto|Débito/pix|Cartão De Crédito)\s*\(\s*(X?)\s*\)\s*(À VISTA|\d+\s*\+\s*\d+)\s+"
    rf"({DINHEIRO})\s+({DINHEIRO})\s+({DINHEIRO})\s+([\d,]+)",
    re.M | re.I,
)


def ler_tokio(texto: str) -> Proposta:
    p = Proposta(seguradora="TOKIO", produto=produto(texto))

    if m := re.search(r"Cotação nº\.?\s*(\d+)", texto):
        p.numero = m.group(1)
    else:
        p.problemas.append("nº da cotação não encontrado")

    # "Renova Apólice nº.180 Seguradora:\n000000002691184" → 2691184
    if m := re.search(r"Renova Apólice nº\.?\s*\d*\s*Seguradora:\s*(\d{6,})", texto):
        p.apolice_anterior = str(int(m.group(1)))
    else:
        p.problemas.append(f"{SEM_APOLICE_ANTERIOR} (Renova Apólice nº) não encontrado")

    if m := re.search(r"A\(o\)\s*\n(?:.*\n){0,4}?(.+?)\s+-\s+(" + CNPJ + r")\s*$", texto, re.M):
        p.razao_social = m.group(1).strip()
        p.cnpj = so_digitos(m.group(2))
    else:
        p.problemas.append("CNPJ do segurado não encontrado")

    if m := re.search(r"Resumo do Prêmio[\s\S]{0,300}?^(" + DINHEIRO + r")\s+(" + DINHEIRO + r")\s+("
                      + DINHEIRO + r")\s+(" + DINHEIRO + r")\s+(" + DINHEIRO + r")\s*$", texto, re.M):
        liquido, adicional, fracionamento, iof, total = (dinheiro(m.group(i)) for i in range(1, 6))
        p.premio_liquido, p.iof, p.premio_total = liquido, iof, total
        if liquido + adicional + fracionamento + iof != total:
            p.problemas.append("Resumo do Prêmio não fecha (líquido + adicional + fracionamento + IOF ≠ total)")
    else:
        p.problemas.append("Resumo do Prêmio não encontrado")

    if m := re.search(r"Comercialização\s*\n\s*(\d{2})\d{2}", texto):
        p.comissao = int(m.group(1))
    else:
        p.problemas.append("comissão (Comercialização) não encontrada")

    vistos = set()
    for m in _OPCAO_TOKIO.finditer(texto):
        forma = _FORMA_TOKIO[m.group(1).lower()]
        chave = (forma, re.sub(r"\s", "", m.group(3).upper()))
        if chave in vistos:  # o cabeçalho de página repete; a tabela não
            continue
        vistos.add(chave)
        p.opcoes.append(OpcaoPagamento(
            forma=forma,
            parcelas=_plano_para_parcelas(m.group(3)),
            primeira=dinheiro(m.group(4)),
            demais=dinheiro(m.group(5)),
            premio_total=dinheiro(m.group(6)),
            iof=p.iof,
            premio_liquido=p.premio_liquido if dinheiro(m.group(6)) == p.premio_total else None,
            marcada=m.group(2).upper() == "X",
            descricao=f"{m.group(1)} {m.group(3)}",
        ))
    if not p.opcoes:
        p.problemas.append("tabela de Opções de Pagamento não encontrada")
    return p


# ---------------------------------------------------------------- Porto

def _forma_porto(descricao: str) -> str:
    d = descricao.upper()
    if "PORTO" in d and "CARTAO" in d:
        return "cartao_porto"
    if "CARTAO" in d or "CARTÃO" in d:
        return "cartao"
    if "BOLETO" in d:
        return "boleto"
    if "ADC" in d or "DEBITO" in d or "DÉBITO" in d:
        return "debito"
    return "outra"


_OPCAO_PORTO = re.compile(
    r"^(\d{1,2})\s*x\s+(.+?)\s+" + r"\s+".join([rf"R\$\s*({DINHEIRO})"] * 6) + r"\s*$",
    re.M,
)


def ler_porto(texto: str) -> Proposta:
    p = Proposta(seguradora="PORTO", produto=produto(texto))

    # Orçamento: "NÚMERO DO ORÇAMENTO\n14/11/2026 118610821"; Proposta de Seguro (Q77): "...\nPROPOSTA DE SEGURO 118653373"
    if m := re.search(r"NÚMERO DO ORÇAMENTO\s*\n[^\n]*?(?<![\d/.])(\d{6,})(?![\d/])", texto):
        p.numero = m.group(1)
    else:
        p.problemas.append("nº do orçamento não encontrado")

    if m := re.search(r"APÓLICE A SER RENOVADA\s*\n.*NÚMERO DA APÓLICE.*\n\s*\d+\s+(\d+)", texto):
        p.apolice_anterior = str(int(m.group(1)))
    else:
        p.problemas.append(f"{SEM_APOLICE_ANTERIOR} (Informações da apólice a ser renovada) não encontrado")

    # Orçamento: "DADOS DO PROPONENTE\n<cabeçalho>\n<NOME> JURÍDICA <CNPJ>";
    # Proposta de Seguro (Q77): "DADOS GERAIS\nPROPONENTE TIPO DE PESSOA CNPJ\n<NOME> JURÍDICA 07285428/0001-77"
    if m := re.search(r"(?:DADOS DO PROPONENTE\s*\n.*|PROPONENTE\s+TIPO DE PESSOA\s+CNPJ)\s*\n(.+?)\s+JUR[ÍI]DICA\s+("
                      + CNPJ + r")", texto):
        p.razao_social = m.group(1).strip()
        p.cnpj = so_digitos(m.group(2))
    else:
        p.problemas.append("CNPJ do proponente não encontrado")

    if m := re.search(r"(\d{2}/\d{2}/\d{4})\s+RENOVA[CÇ][AÃ]O", texto):
        p.vigencia_inicio = m.group(1)
        p.vigencia_fim = mais_um_ano(m.group(1))
    else:
        p.problemas.append("início de vigência não encontrado")

    if m := re.search(r" - CO(\d{1,2}) - ", texto):   # "CO5" = 5%, "CO20" = 20%
        p.comissao = int(m.group(1))
    else:
        p.problemas.append("comissão (COnn no cabeçalho) não encontrada")

    liquido_total = custo = None
    if m := re.search(r"DEMONSTRATIVO DE PRÊMIO GERAL\s*\n.*\n" + r"\s*".join([rf"R\$\s*({DINHEIRO})"] * 6), texto):
        _, _, liquido_total, custo, iof, total = (dinheiro(m.group(i)) for i in range(1, 7))
        p.premio_liquido, p.iof, p.premio_total = liquido_total, iof, total
        if liquido_total + custo + iof != total:
            p.problemas.append("Demonstrativo de prêmio geral não fecha (líquido + custo + IOF ≠ total)")
    else:
        p.problemas.append("Demonstrativo de prêmio geral não encontrado")

    # Cada forma tem seu próprio total: à vista e cartão Porto têm desconto e IOF diferentes do demonstrativo geral.
    # total da forma = soma das parcelas; líquido da forma = total − IOF − custo − juros − encargos.
    for m in _OPCAO_PORTO.finditer(texto):
        n = int(m.group(1))
        primeira, demais, juros, encargos, custo_op, iof_op = (dinheiro(m.group(i)) for i in range(3, 9))
        total_op = primeira + demais * (n - 1)
        p.opcoes.append(OpcaoPagamento(
            forma=_forma_porto(m.group(2)),
            parcelas=n,
            primeira=primeira,
            demais=demais,
            premio_total=total_op,
            iof=iof_op,
            premio_liquido=total_op - iof_op - custo_op - juros - encargos,
            descricao=f"{m.group(1)} x {m.group(2)}",
        ))
    if not p.opcoes and (op := _forma_contratada_porto(texto, custo)):
        p.opcoes.append(op)          # Proposta de Seguro: só a forma contratada, já marcada
    if not p.opcoes:
        p.problemas.append("tabela de Formas de Pagamento não encontrada")
    return p


# Q77: a "Proposta de Seguro" da Porto não tem a tabela de opções do Orçamento, só a forma contratada:
#   FORMA DE PAGAMENTO / 41 - 6 x BOLETO BANCARIO / VALOR DAS PARCELAS /
#   1º PARCELA DEMAIS PARCELAS(R$) JUROS I.O.F. ENCARGOS / R$ 658,74 R$ 658,75 R$ 0,00 R$ 271,65 R$ 0,00
_FORMA_CONTRATADA_PORTO = re.compile(
    r"FORMA DE PAGAMENTO\s*\n\s*(?:\d+\s*-\s*)?(\d{1,2})\s*x\s*(.+?)\s*\n\s*VALOR DAS PARCELAS\s*\n.*\n\s*"
    + r"\s+".join([rf"R\$\s*({DINHEIRO})"] * 5))


def _forma_contratada_porto(texto: str, custo: Decimal | None) -> OpcaoPagamento | None:
    m = _FORMA_CONTRATADA_PORTO.search(texto)
    if not m:
        return None
    n = int(m.group(1))
    primeira, demais, juros, iof, encargos = (dinheiro(m.group(i)) for i in range(3, 8))
    total = primeira + demais * (n - 1)
    return OpcaoPagamento(forma=_forma_porto(m.group(2)), parcelas=n, primeira=primeira, demais=demais,
                          premio_total=total, iof=iof, premio_liquido=total - iof - (custo or 0) - juros - encargos,
                          marcada=True, descricao=f"{n} x {m.group(2).strip()} (forma contratada na proposta)")


def ler_proposta(texto: str) -> Proposta:
    tipo = classificar(texto)
    if tipo == "PROPOSTA_TOKIO":
        return ler_tokio(texto)
    if tipo == "PROPOSTA_PORTO":
        return ler_porto(texto)
    raise ValueError(f"não é uma proposta: {tipo}")


def soma_parcelas_confere(op: OpcaoPagamento, tolerancia: Decimal = Decimal("0.10")) -> bool:
    if op.premio_total is None:
        return True
    soma = op.primeira + op.demais * (op.parcelas - 1)
    return abs(soma - op.premio_total) <= tolerancia
