"""Leitura do acordo: separa a fala do CLIENTE e extrai a escolha de parcelas/forma de pagamento.

Regra de ouro (§6.1): vale a última escolha explícita do cliente; a marcação (X) da proposta é ignorada.
"""
from __future__ import annotations

import re
from pathlib import Path

from .modelos import Escolha
from .numeros import CNPJ, so_digitos
from .pdftexto import Linha, linhas, texto

CARIMBO = re.compile(r"^\d{2}/\d{2}/\d{4}\s+[aáà]s\s+\d{2}:\d{2}(:\d{2})?$", re.I)

# ---------------------------------------------------------------- separação das falas


def mensagens_chat(ls: list[Linha]) -> list[tuple[str, str]]:
    """Histórico de Atendimento → [(lado, texto)] em ordem de leitura; lado = 'cliente' | 'atendente'.

    Coluna esquerda = contato (cliente); a coluna que começa no cabeçalho 'Atendente' = atendente.
    Cada mensagem é: cabeçalho (remetente) + carimbo 'dd/mm/aaaa ás hh:mm:ss' + corpo.
    """
    cab = next((l for l in ls if l.texto.strip() == "Atendente"), None)
    limite = (cab.x0 if cab else 0.25) - 0.03

    msgs: list[list] = []                 # [lado, [linhas]]
    pendente = {"cliente": [], "atendente": []}
    cab_cliente: set[str] = set()
    nomes_atendente: set[str] = set()
    for l in ls:
        t = l.texto.strip()
        if t.startswith(("Histórico de Atendimento", "Contato")) or t == "Atendente":
            continue
        if re.fullmatch(r"\d+", t) and l.top < 60:  # nº de página
            continue
        lado = "cliente" if l.x0 < limite else "atendente"
        atual = msgs[-1] if msgs else None
        if CARIMBO.match(t):
            if lado == "cliente":
                if not cab_cliente:
                    cab_cliente = set(pendente["cliente"]) or ({atual[1][-1]} if atual and atual[0] == lado and atual[1] else set())
                if atual and atual[0] == lado:
                    while atual[1] and atual[1][-1] in cab_cliente:
                        atual[1].pop()
            else:
                if pendente["atendente"]:
                    nomes_atendente.add(pendente["atendente"][-1])
                elif atual and atual[0] == lado and atual[1]:
                    nomes_atendente.add(atual[1].pop())
            pendente[lado] = []
            msgs.append([lado, []])
            continue
        if atual and atual[0] == lado:
            atual[1].append(t)
        else:
            pendente[lado].append(t)
    return [(lado, "\n".join(ls_).strip()) for lado, ls_ in msgs if "\n".join(ls_).strip()]


def mensagens_cliente_chat(ls: list[Linha]) -> list[str]:
    return [t for lado, t in mensagens_chat(ls) if lado == "cliente"]


def mensagens_cliente_email(txt: str) -> list[str]:
    """E-mail impresso (Gmail): a resposta do cliente vem antes do primeiro 'De:' citado."""
    ls = [l.strip() for l in txt.splitlines()]
    inicio = None
    for i, l in enumerate(ls):
        m = re.search(r"<([^>]+@[^>]+)>", l)
        if m and "grupoprotege" not in m.group(1).lower():
            inicio = i + 1
            break
    if inicio is None:
        return []
    corpo = []
    for l in ls[inicio:]:
        if re.match(r"^(De|From|Para|To|Cc):", l) and corpo:
            if l.startswith(("De:", "From:")):
                break
            continue
        if re.match(r"^(Para|Cc):", l):
            continue
        corpo.append(l)
    return ["\n".join(corpo).strip()] if corpo else []


# ---------------------------------------------------------------- escolha do cliente

_SOMA = re.compile(r"(?<![\d/.,])(\d{1,2})\s*(?:\+|e\s+mais|mais)\s*(\d{1,2})(?![\d/.,])", re.I)
_OU = re.compile(r"(?<![\d/.,])(\d{1,2})\s+ou\s+(\d{1,2})(?![\d/.,])", re.I)
_ACEITE = re.compile(r"\b(sim|pode|podemos|fechad[oa]|fechar|fecha|ok|isso|aceit[oa]|perfeito|combinado|beleza|certo|"
                     r"de acordo|t[áa] bom|tudo bem|pode ser)\b", re.I)
# cliente que responde a oferta só com um emoji de "positivo" (Q63). No PDF do Histórico de Atendimento o 👍 sai
# como caractere do Font Awesome (U+F087 thumbs-o-up / U+F164 thumbs-up); no e-mail, como emoji de verdade.
_EMOJI_ACEITE = {"\uf087": "👍", "\uf164": "👍", "\U0001F44D": "👍", "\U0001F44C": "👌", "\u2705": "✅",
                 "\u2714": "✔️", "\U0001F91D": "🤝"}
_EMOJI = "[" + "".join(_EMOJI_ACEITE) + "]"
_ENFEITE = "[\\s\ufe0f\U0001F3FB-\U0001F3FF!.]"   # espaço, variação de emoji, tom de pele, "!" e "."
# só emoji(s) de aceite, com enfeites em volta; precisa ter PELO MENOS um emoji ("." ou "!" sozinho não é aceite)
_SO_EMOJI_ACEITE = re.compile(f"^{_ENFEITE}*{_EMOJI}(?:{_EMOJI}|{_ENFEITE})*$")
_FECHO_PADRAO = re.compile(r"a ap[óo]lice e os boletos", re.I)  # frase-padrão do consultor, não indica forma
_N = re.compile(r"(?<![\d/.,])(\d{1,2})\s*(?:x|vezes|parcelas?|parc\b)", re.I)
_A_VISTA = re.compile(r"\b[àa]\s+vista\b|parcela [úu]nica|pagamento [úu]nico", re.I)
_SO_NUMERO = re.compile(r"^\s*(\d{1,2})\s*[.!]?\s*$")

_FORMAS = [
    ("cartao_porto", re.compile(r"cart[ãa]o\s+(de\s+cr[ée]dito\s+)?porto", re.I)),
    ("cartao", re.compile(r"cart[ãa]o|cr[ée]dito", re.I)),
    ("boleto", re.compile(r"boleto", re.I)),
    ("pix", re.compile(r"\bpix\b", re.I)),
    ("debito", re.compile(r"d[ée]bito", re.I)),
]


def _parcelas_na_mensagem(msg: str) -> tuple[set[int], str]:
    achados: set[int] = set()
    trechos = []
    ocupado: list[tuple[int, int]] = []
    for m in _SOMA.finditer(msg):
        n = int(m.group(1)) + int(m.group(2))
        if 1 <= n <= 12:
            achados.add(n)
            trechos.append(m.group(0))
            ocupado.append(m.span())
    for m in _N.finditer(msg):
        if any(a <= m.start() < b for a, b in ocupado):
            continue
        n = int(m.group(1))
        if 1 <= n <= 12:
            achados.add(n)
            trechos.append(m.group(0))
    for m in _OU.finditer(msg):
        for g in (1, 2):
            n = int(m.group(g))
            if 1 <= n <= 12:
                achados.add(n)
        trechos.append(m.group(0))
    if _A_VISTA.search(msg):
        achados.add(1)
        trechos.append(_A_VISTA.search(msg).group(0))
    if not achados and (m := _SO_NUMERO.match(msg)):
        n = int(m.group(1))
        if 1 <= n <= 12:
            achados.add(n)
            trechos.append(m.group(0).strip())
    return achados, ", ".join(trechos)


def _forma_na_mensagem(msg: str) -> str | None:
    msg = _FECHO_PADRAO.sub("", msg)
    for nome, rx in _FORMAS:
        if rx.search(msg):
            return nome
    return None


def _curto(msg: str) -> str:
    for cod, emoji in _EMOJI_ACEITE.items():
        msg = msg.replace(cod, emoji)
    return msg.replace("\n", " ")[:160]


def _aceite(msg: str) -> bool:
    """'Pode sim', 'Fechado'… ou só um 👍 (Q63)."""
    return bool(_ACEITE.search(msg) or _SO_EMOJI_ACEITE.match(msg))


def escolha_combinada(conversa: list[tuple[str, str]]) -> Escolha:
    """Percorre a conversa e devolve a última condição combinada (Q6 + Q31).

    - Fala explícita do CLIENTE com parcelas → vale (a mais recente vence).
    - Oferta explícita do CONSULTOR com parcelas E forma ("Podemos fechar em 1+5x no boleto?")
      seguida de aceite do cliente ("Pode sim", "Fechado") → vale como "oferta aceita".
    - Forma: a da condição combinada; senão a última citada pelo cliente; senão boleto presumido (Q32).
    """
    e = Escolha(mensagens_cliente=sum(1 for lado, _ in conversa if lado == "cliente"))
    oferta: tuple[int, str, str] | None = None
    for lado, msg in conversa:
        achados, _ = _parcelas_na_mensagem(msg)
        forma = _forma_na_mensagem(msg)
        if lado == "atendente":
            if len(achados) == 1 and forma:
                oferta = (next(iter(achados)), forma, msg)
            continue
        # cliente
        if achados:
            oferta = None
            e.trecho_parcelas = _curto(msg)
            e.origem = "cliente"
            if len(achados) == 1:
                e.parcelas, e.ambigua = next(iter(achados)), False
            else:
                e.parcelas, e.ambigua = None, True
            if forma:
                e.forma, e.trecho_forma = forma, _curto(msg)
        elif oferta and _aceite(msg):
            n, f, txt = oferta
            e.parcelas, e.ambigua, e.origem = n, False, "oferta aceita"
            e.trecho_parcelas = f"{_curto(txt)} → cliente: {_curto(msg)}"
            e.forma, e.trecho_forma = f, _curto(txt)
            oferta = None
        if forma and not achados:
            e.forma, e.trecho_forma = forma, _curto(msg)
    if e.forma is None and (e.parcelas or e.ambigua):
        e.forma, e.forma_presumida = "boleto", True
    return e


def escolha_do_cliente(mensagens: list[str]) -> Escolha:
    return escolha_combinada([("cliente", m) for m in mensagens])


def cnpjs_citados(txt: str) -> set[str]:
    return {so_digitos(m) for m in re.findall(CNPJ, txt)}


def ler_acordo(caminho: Path, tipo: str) -> tuple[Escolha, set[str]]:
    txt = texto(caminho)
    if tipo == "ACORDO_EMAIL":
        conversa = [("cliente", m) for m in mensagens_cliente_email(txt)]
    else:
        conversa = mensagens_chat(linhas(caminho))
    return escolha_combinada(conversa), cnpjs_citados(txt)
