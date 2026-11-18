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
    vigencia_inicio: str = "31/12/2026"
    vigencia_fim: str = "31/12/2027"
    url_sgcor: str = "https://grupoprotege.sgcor.com.br/"

    def bonus_para(self, comissao: int) -> Decimal | None:
        for f in self.bonus:
            if f.contem(comissao):
                return f.valor
        return None


def carregar(caminho: Path = PADRAO) -> Config:
    dados = tomllib.loads(caminho.read_text(encoding="utf-8"))
    sg = dict(dados["sgcor"])
    url = str(sg.pop("url", "https://grupoprotege.sgcor.com.br/"))
    return Config(
        primeira_parcela=dados["datas"]["primeira_parcela"],
        apolice_provisoria=str(dados["apolice"]["provisoria"]),
        bonus=[FaixaBonus(f.get("de"), f.get("ate"), Decimal(f["valor"])) for f in dados["bonus"]],
        cobranca={k: int(v) for k, v in dados["cobranca"].items()},
        sgcor={k: int(v) for k, v in sg.items()},
        vigencia_inicio=dados["datas"].get("vigencia_inicio", "31/12/2026"),
        vigencia_fim=dados["datas"].get("vigencia_fim", "31/12/2027"),
        url_sgcor=url if url.endswith("/") else url + "/",
    )
