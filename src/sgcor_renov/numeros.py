"""Conversões de números, datas e CNPJ no formato brasileiro."""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

DINHEIRO = r"\d{1,3}(?:\.\d{3})*,\d{2}"
CNPJ = r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}"


def dinheiro(valor: str) -> Decimal:
    try:
        return Decimal(valor.strip().replace(".", "").replace(",", "."))
    except InvalidOperation as e:
        raise ValueError(f"valor inválido: {valor!r}") from e


def formatar_dinheiro(valor: Decimal | None) -> str:
    if valor is None:
        return ""
    s = f"{valor:,.2f}"
    return s.replace(",", "_").replace(".", ",").replace("_", ".")


def so_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto)


def formatar_cnpj(digitos: str | None) -> str:
    if not digitos or len(digitos) != 14:
        return digitos or ""
    d = digitos
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


# CNPJ no nome da pasta (o Windows não aceita "/" em nome de pasta: vem "-", ".", "_" ou espaço no lugar)
_CNPJ_NO_NOME = re.compile(r"(?<!\d)\d{2}[.\s_]?\d{3}[.\s_]?\d{3}[/\\\-.\s_]?\d{4}[-.\s_]?\d{2}(?!\d)")


def separar_cnpj(nome: str) -> tuple[str, str | None]:
    """Q72: "LOTERICA X - 11.158.635-0002-19" → ("LOTERICA X", "11158635000219"); "11158635000219" → ("", ...);
    sem CNPJ → (nome, None)."""
    m = _CNPJ_NO_NOME.search(nome)
    if not m:
        return nome, None
    resto = (nome[:m.start()] + " " + nome[m.end():]).strip(" -–_.")
    return re.sub(r"\s{2,}", " ", resto).strip(" -–_."), so_digitos(m.group(0))


def mais_um_ano(data_br: str) -> str:
    d, m, a = (int(x) for x in data_br.split("/"))
    try:
        nova = date(a + 1, m, d)
    except ValueError:  # 29/02
        nova = date(a + 1, m, d - 1)
    return nova.strftime("%d/%m/%Y")
