"""Relatório da F1: o que está pronto para cadastrar e o que está pendente.

Uso:
    python -m sgcor_renov.relatorio "C:\\...\\FECHADOS PORTO" "C:\\...\\FECHADOS TOKIO" [--csv saida\\relatorio.csv]
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from .config import carregar
from .modelos import Caso
from .numeros import formatar_cnpj, formatar_dinheiro
from .scanner import varrer

COLUNAS = ["Status", "Seguradora", "Lotérica", "CNPJ", "Apólice anterior", "Proposta nº", "Parcelas", "Forma",
           "Cobrança SGCOR", "Prêmio líquido", "IOF", "Prêmio total", "Comissão %", "Bônus", "Pendências", "Avisos"]


def linha(c: Caso) -> list[str]:
    p = c.proposta
    return [
        c.status, c.seguradora, c.nome,
        formatar_cnpj(p.cnpj) if p else "", (p.apolice_anterior or "") if p else "", (p.numero or "") if p else "",
        str(c.parcelas or ""), c.forma or "", str(c.cobranca_id or ""),
        formatar_dinheiro(c.premio_liquido), formatar_dinheiro(c.iof), formatar_dinheiro(c.premio_total),
        str(p.comissao) if p and p.comissao is not None else "", formatar_dinheiro(c.bonus),
        " | ".join(c.pendencias), " | ".join(c.avisos),
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pastas", nargs="+", type=Path)
    ap.add_argument("--csv", type=Path)
    args = ap.parse_args(argv)

    casos = varrer(args.pastas, carregar())
    prontos = [c for c in casos if c.status == "Pronto"]
    print(f"{len(casos)} lotéricas · {len(prontos)} prontas · {len(casos) - len(prontos)} pendentes\n")
    for c in casos:
        p = c.proposta
        resumo = (f"{c.parcelas or '?'}x {c.forma or '?'} · total {formatar_dinheiro(c.premio_total) or '?'}"
                  f" · comissão {p.comissao if p else '?'}% → bônus {formatar_dinheiro(c.bonus) or '?'}")
        print(f"[{c.status:8}] {c.seguradora:5} {c.nome[:45]:45} {resumo}")
        for pend in c.pendencias:
            print(f"           ⚠ {pend}")
        for av in c.avisos:
            print(f"           · {av}")

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(COLUNAS)
            w.writerows(linha(c) for c in casos)
        print(f"\nCSV: {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
