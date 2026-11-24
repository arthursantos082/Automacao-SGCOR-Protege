"""Carrega a configuração editável (config/padrao.toml)."""
from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

# no .exe (PyInstaller) a pasta config/ fica ao lado do AutoCOR.exe, editável pela TI
RAIZ = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
PADRAO = RAIZ / "config" / "padrao.toml"
AJUSTAR_PADRAO = ("incendio", "valores_interior", "valores_transito")
# Q71: ramos em que a apólice anterior pode estar quando não está no ramo lotérico da seguradora
RAMOS_PADRAO = ("LOTÉRICO", "CAIXA AQUI")
# Q71: ao incluir coberturas (renovação vinda de outro ramo), a linha do SGCOR usada para cada tipo
INCLUIR_PADRAO = {"incendio": "INCÊNDIO, RAIO, EXPLOSÃO, IMPLOSÃO E FUMAÇA",
                  "valores_interior": "GERPA - SUB. DE VALORES NO INTERIOR DO ESTABELECIMENTO",
                  "valores_transito": "GERPA - SUB. DE VALORES FORA DO ESTABELECIMENTO"}


@dataclass
class FaixaBonus:
    de: int | None
    ate: int | None
    valor: Decimal

    def contem(self, comissao: int) -> bool:
        return (self.de is None or comissao >= self.de) and (self.ate is None or comissao <= self.ate)


# Q90: vencimento da 1ª parcela por seguradora. Fica também aqui porque a atualização mantém a config antiga da
# máquina (a chave antiga "primeira_parcela", igual para as duas, não vale mais)
PRIMEIRA_PARCELA_PADRAO = {"PORTO": "11/01/2027", "TOKIO": "15/01/2027"}


@dataclass
class Config:
    apolice_provisoria: str
    bonus: list[FaixaBonus]
    cobranca: dict[str, int]
    sgcor: dict[str, int]
    vigencia_inicio: str = "31/12/2026"
    vigencia_fim: str = "31/12/2027"
    url_sgcor: str = "https://grupoprotege.sgcor.com.br/"
    navegador: str = "chrome"
    espera_login: int = 300
    # Q59: só estes tipos de cobertura têm o LMI ajustado; o resto fica como veio no SGCOR
    coberturas_ajustar: tuple[str, ...] = AJUSTAR_PADRAO
    ramos_renovacao: tuple[str, ...] = RAMOS_PADRAO
    coberturas_incluir: dict | None = None       # tipo → nome da cobertura no SGCOR (None = INCLUIR_PADRAO)
    repositorio: str = "arthursantos082/Automacao-SGCOR-Protege"   # Releases com as atualizações
    primeira_parcela: dict[str, str] | None = None   # seguradora → vencimento da 1ª parcela (None = o padrão)

    def primeira_parcela_de(self, seguradora: str) -> str:
        return {**PRIMEIRA_PARCELA_PADRAO, **(self.primeira_parcela or {})}[seguradora.upper()]

    def bonus_para(self, comissao: int) -> Decimal | None:
        for f in self.bonus:
            if f.contem(comissao):
                return f.valor
        return None


def carregar(caminho: Path = PADRAO) -> Config:
    dados = tomllib.loads(caminho.read_text(encoding="utf-8"))
    sg = dict(dados["sgcor"])
    url = str(sg.pop("url", "https://grupoprotege.sgcor.com.br/"))
    navegador = str(sg.pop("navegador", "chrome"))
    espera_login = int(sg.pop("espera_login", 300))
    return Config(
        apolice_provisoria=str(dados["apolice"]["provisoria"]),
        bonus=[FaixaBonus(f.get("de"), f.get("ate"), Decimal(f["valor"])) for f in dados["bonus"]],
        cobranca={k: int(v) for k, v in dados["cobranca"].items()},
        sgcor={k: int(v) for k, v in sg.items()},
        vigencia_inicio=dados["datas"].get("vigencia_inicio", "31/12/2026"),
        vigencia_fim=dados["datas"].get("vigencia_fim", "31/12/2027"),
        url_sgcor=url if url.endswith("/") else url + "/",
        navegador=navegador,
        espera_login=espera_login,
        # config antiga (instalada antes da 1.1.0) não tem a seção: vale o padrão
        coberturas_ajustar=tuple(dados.get("coberturas", {}).get("ajustar", AJUSTAR_PADRAO)),
        ramos_renovacao=tuple(r.upper() for r in dados.get("renovacao", {}).get("ramos", RAMOS_PADRAO)),
        coberturas_incluir={**INCLUIR_PADRAO, **dados.get("coberturas", {}).get("incluir", {})},
        repositorio=str(dados.get("atualizacao", {}).get("repositorio", "arthursantos082/Automacao-SGCOR-Protege")),
        primeira_parcela={seg: str(dados["datas"].get(f"primeira_parcela_{seg.lower()}", padrao))
                          for seg, padrao in PRIMEIRA_PARCELA_PADRAO.items()},
    )
