"""Carrega a configuração editável (config/padrao.toml)."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
PADRAO = RAIZ / "config" / "padrao.toml"


@dataclass
class FaixaBonus:
    de: int | None
    ate: int | None
    valor: Decimal

    def contem(self, comissao: int) -> bool:
        return (self.de is None or comissao >= self.de) and (self.ate is None or comissao <= self.ate)


@dataclass
class Config:
    primeira_parcela: str
    apolice_provisoria: str
    bonus: list[FaixaBonus]
    cobranca: dict[str, int]
    sgcor: dict[str, int]

    def bonus_para(self, comissao: int) -> Decimal | None:
        for f in self.bonus:
            if f.contem(comissao):
                return f.valor
        return None


def carregar(caminho: Path = PADRAO) -> Config:
    dados = tomllib.loads(caminho.read_text(encoding="utf-8"))
    return Config(
        primeira_parcela=dados["datas"]["primeira_parcela"],
        apolice_provisoria=str(dados["apolice"]["provisoria"]),
        bonus=[FaixaBonus(f.get("de"), f.get("ate"), Decimal(f["valor"])) for f in dados["bonus"]],
        cobranca={k: int(v) for k, v in dados["cobranca"].items()},
        sgcor={k: int(v) for k, v in dados["sgcor"].items()},
    )
