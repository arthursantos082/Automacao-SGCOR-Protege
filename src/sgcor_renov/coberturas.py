"""Coberturas + LMI das propostas, lidas pela posição das colunas (os nomes quebram em várias linhas)."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pdfplumber

from .numeros import DINHEIRO, dinheiro

_LMI = re.compile(rf"^R\$\s*({DINHEIRO})")


@dataclass
class Cobertura:
    nome: str
    lmi: Decimal


@dataclass
class _Linha:
    top: float
    nome: str
    lmi: str


def normalizar(nome: str) -> str:
    """Maiúsculas, sem acento e sem pontuação — para casar nomes no dicionário."""
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9 ]+", " ", s).upper()
    return re.sub(r"\s+", " ", s).strip()


def _linhas_da_pagina(page, x_lmi: float, x_dir: float, top_ini: float, top_fim: float) -> list[_Linha]:
    palavras = [w for w in page.extract_words() if top_ini < w["top"] < top_fim]
    palavras.sort(key=lambda w: (round(w["top"]), w["x0"]))
    linhas: list[list[dict]] = []
    for w in palavras:
        if linhas and abs(w["top"] - linhas[-1][0]["top"]) <= 2.5:
            linhas[-1].append(w)
        else:
            linhas.append([w])
    out = []
    for ws in linhas:
        ws.sort(key=lambda w: w["x0"])
        # LMI = primeiro "R$ <valor>" antes da coluna seguinte (franquia/prêmio); o nome é o que vem antes dele.
        # A margem de 15pt evita pegar o mínimo da franquia, que começa logo antes do cabeçalho "Franquia".
        i = next((k for k in range(len(ws) - 1)
                  if ws[k]["text"] == "R$" and re.fullmatch(DINHEIRO, ws[k + 1]["text"]) and ws[k]["x0"] < x_dir - 15),
                 None)
        if i is not None:
            nome = " ".join(w["text"] for w in ws[:i])
            lmi = f"R$ {ws[i + 1]['text']}"
        else:
            nome = " ".join(w["text"] for w in ws if w["x0"] < x_lmi - 4)
            lmi = ""
        out.append(_Linha(ws[0]["top"], nome.strip(), lmi))
    return out


def _palavra(page, texto: str):
    return next((w for w in page.extract_words() if w["text"] == texto), None)


def ler_tokio(caminho: Path) -> list[Cobertura]:
    """Tabelas 'Cobertura Contratada | Limite Máximo de Indenização | Franquia' (podem continuar na página seguinte).
    O LMI fica na 1ª linha de cada cobertura; as linhas seguintes só continuam o nome."""
    itens: list[list] = []   # [nome, lmi]
    with pdfplumber.open(caminho) as doc:
        for page in doc.pages:
            ws = page.extract_words()
            cab = next((w for w in ws if w["text"] == "Contratada"), None)
            if not cab:
                continue
            lim = next((w for w in ws if w["text"] == "Limite" and abs(w["top"] - cab["top"]) < 3), None)
            fra = next((w for w in ws if w["text"].startswith("Franquia") and abs(w["top"] - cab["top"]) < 3), None)
            if not lim or not fra:
                continue
            fim = next((w["top"] for w in ws if w["top"] > cab["top"] and w["text"] in ("Prêmio", "Tokio")
                        and w["x0"] < lim["x0"]), page.height)
            for l in _linhas_da_pagina(page, lim["x0"], fra["x0"], cab["top"] + 14, fim):
                if (m := _LMI.match(l.lmi)) and l.nome:
                    itens.append([l.nome, dinheiro(m.group(1))])
                elif itens and l.nome and not l.lmi and l.top > cab["top"] + 14:
                    itens[-1][0] += " " + l.nome
    return [Cobertura(re.sub(r"\s+", " ", n).strip(" ,"), v) for n, v in itens]


_FIM_PORTO = ("COBERTURA DE DESPESAS FIXAS DECORRENTES", "COBERTURA DE LUCROS", "CLÁUSULA", "CLAUSULA",
              "DEMONSTRATIVO", "SERVIÇOS")


def ler_porto(caminho: Path) -> list[Cobertura]:
    """Tabela 'COBERTURA | L.M.I. | PRÊMIO | P.O.S.'. O nome longo quebra acima e abaixo da linha do LMI,
    então cada linha só-de-nome vai para a linha com LMI mais próxima na vertical."""
    with pdfplumber.open(caminho) as doc:
        for page in doc.pages:
            ws = page.extract_words()
            cab = next((w for w in ws if w["text"] == "L.M.I."), None)
            if not cab:
                continue
            # a coluna do prêmio se chama "PRÊMIO" (Orçamento/Proposta) ou "ESTIMATIVA" (Estimativa — Q81)
            pre = next((w for w in ws if w["text"] in ("PRÊMIO", "ESTIMATIVA") and abs(w["top"] - cab["top"]) < 3),
                       None)
            if not pre:
                continue
            fim = page.height
            for w in ws:
                if w["top"] > cab["top"] + 5:
                    linha = " ".join(x["text"] for x in sorted((x for x in ws if abs(x["top"] - w["top"]) < 2.5),
                                                               key=lambda x: x["x0"]))
                    if linha.upper().startswith(_FIM_PORTO):
                        fim = min(fim, w["top"] - 1)
            linhas = _linhas_da_pagina(page, cab["x0"], pre["x0"], cab["top"] + 5, fim)
            com_lmi = [l for l in linhas if _LMI.match(l.lmi)]
            nomes: dict[int, list[tuple[float, str]]] = {id(l): [(l.top, l.nome)] for l in com_lmi}
            for l in linhas:
                if l in com_lmi or not l.nome or l.lmi:
                    continue
                alvo = min(com_lmi, key=lambda c: abs(c.top - l.top), default=None)
                if alvo:
                    nomes[id(alvo)].append((l.top, l.nome))
            out = []
            for l in com_lmi:
                nome = " ".join(t for _, t in sorted(nomes[id(l)]) if t)
                if normalizar(nome).startswith("VALOR EM RISCO DECLARADO"):
                    continue  # é o VR declarado, não uma cobertura
                out.append(Cobertura(re.sub(r"\s+", " ", nome).strip(" ,"), dinheiro(_LMI.match(l.lmi).group(1))))
            return out
    return []


def ler(caminho: Path, seguradora: str) -> list[Cobertura]:
    return ler_porto(caminho) if seguradora == "PORTO" else ler_tokio(caminho)


# ---------------------------------------------------------------- dicionário (config/coberturas.toml)

@dataclass
class Tipo:
    chave: str
    descricao: str
    nomes: dict[str, list[str]]     # origem (porto|tokio|sgcor) → inícios de nome normalizados
    confirmar: bool = False


class Dicionario:
    def __init__(self, tipos: list[Tipo]):
        self.tipos = tipos

    @classmethod
    def carregar(cls, caminho: Path | None = None) -> "Dicionario":
        import tomllib

        from .config import RAIZ
        caminho = caminho or RAIZ / "config" / "coberturas.toml"
        dados = tomllib.loads(caminho.read_text(encoding="utf-8"))
        return cls([Tipo(t["chave"], t.get("descricao", ""),
                         {o: [normalizar(n) for n in t.get(o, [])] for o in ("porto", "tokio", "sgcor")},
                         bool(t.get("confirmar"))) for t in dados["tipo"]])

    def tipo_de(self, nome: str, origem: str) -> Tipo | None:
        """origem: 'porto' | 'tokio' | 'sgcor'. Vence o início de nome mais longo (ex.: RC EMPREGADOR antes de RC)."""
        n = normalizar(re.sub(r"^\s*\d+\s*-\s*(\d+\s+)?", "", nome))  # SGCOR: "456 - GERPA..." / "778 - 7 GERPA..."
        melhor: tuple[int, Tipo] | None = None
        for t in self.tipos:
            for p in t.nomes[origem]:
                if p and (n == p or n.startswith(p + " ")) and (melhor is None or len(p) > melhor[0]):
                    melhor = (len(p), t)
        return melhor[1] if melhor else None
