"""Varre as pastas FECHADOS PORTO / FECHADOS TOKIO e monta um Caso por lotérica."""
from __future__ import annotations

from pathlib import Path

from . import acordo as acordo_mod
from . import propostas as prop_mod
from . import regras
from .config import Config
from .modelos import Caso
from .pdftexto import texto

IGNORAR = ("_CADASTRADOS",)


def seguradora_da_pasta(raiz: Path) -> str:
    nome = raiz.name.upper()
    if "PORTO" in nome:
        return "PORTO"
    if "TOKIO" in nome:
        return "TOKIO"
    raise ValueError(f"pasta raiz sem PORTO/TOKIO no nome: {raiz}")


def soltos(raiz: Path) -> list[Caso]:
    seg = seguradora_da_pasta(raiz)
    casos = []
    for solto in sorted(raiz.glob("*.pdf")):
        c = Caso(seguradora=seg, pasta=solto, nome=solto.stem)
        c.pendencias.append(f"PDF solto na raiz da pasta {raiz.name}: mover para a pasta da lotérica")
        casos.append(c)
    return casos


def pastas_de(raiz: Path) -> list[Path]:
    return sorted(p for p in raiz.iterdir() if p.is_dir() and not p.name.startswith(IGNORAR))


def assinatura(pasta: Path) -> tuple:
    """Muda quando um PDF da pasta é criado, apagado, renomeado ou alterado (para reler só o necessário)."""
    return tuple(sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in pasta.glob("*.pdf")))


def varrer(raizes: list[Path], cfg: Config, ajustes=None) -> list[Caso]:
    """ajustes: função pasta → Ajuste | None (resoluções do consultor guardadas no estado local)."""
    casos: list[Caso] = []
    for raiz in raizes:
        seg = seguradora_da_pasta(raiz)
        casos.extend(soltos(raiz))
        for pasta in pastas_de(raiz):
            casos.append(analisar_pasta(pasta, seg, cfg, ajustes(pasta) if ajustes else None))
    return casos


def analisar_pasta(pasta: Path, seg: str, cfg: Config, ajuste=None) -> Caso:
    c = Caso(seguradora=seg, pasta=pasta, nome=pasta.name)
    pdfs = sorted(pasta.glob("*.pdf"))
    tipos: dict[Path, str] = {}
    textos: dict[Path, str] = {}
    for pdf in pdfs:
        try:
            textos[pdf] = texto(pdf)
        except Exception as e:  # PDF corrompido/protegido
            c.pendencias.append(f"Não foi possível ler {pdf.name}: {e}")
            continue
        tipos[pdf] = prop_mod.classificar(textos[pdf])

    acordos = [p for p, t in tipos.items() if t.startswith("ACORDO")]
    props = [p for p, t in tipos.items() if t.startswith("PROPOSTA")]
    outros = [p for p, t in tipos.items() if t == "DESCONHECIDO"]

    # um PDF que não é proposta, numa pasta com exatamente 1 proposta, é tratado como acordo (ex.: e-mail impresso)
    if not acordos and len(props) == 1 and len(outros) == 1:
        acordos, outros = outros, []
        tipos[acordos[0]] = "ACORDO_EMAIL"
        c.avisos.append(f"Acordo identificado por eliminação: {acordos[0].name}")

    if len(pdfs) != 2:
        c.pendencias.append(f"A pasta tem {len(pdfs)} PDF(s); o esperado são 2 (acordo + proposta)")
    for o in outros:
        c.pendencias.append(f"Não foi possível classificar {o.name} como ACORDO ou PROPOSTA")
    if len(acordos) != 1:
        c.pendencias.append("Acordo não encontrado" if not acordos else f"{len(acordos)} acordos na pasta")
    c.propostas = props
    escolhida = None
    if len(props) == 1:
        escolhida = props[0]
    elif len(props) > 1 and ajuste and ajuste.proposta:
        escolhida = next((p for p in props if p.name == ajuste.proposta), None)
        if escolhida:
            c.avisos.append(f"Proposta final escolhida pelo consultor: {escolhida.name}")
    if not props:
        c.pendencias.append("Proposta não encontrada")
    elif escolhida is None:
        c.pendencias.append(f"{len(props)} propostas na pasta: escolher a final (Q9)")
    # pasta com 2+ propostas resolvida pelo consultor não conta como "≠ 2 PDFs"
    if escolhida and len(pdfs) == len(props) + 1 and len(props) > 1:
        c.pendencias = [p for p in c.pendencias if not p.startswith("A pasta tem")]
    c.proposta_escolhida = escolhida

    if escolhida:
        c.proposta = prop_mod.ler_proposta(textos[escolhida])
        if c.proposta.seguradora != seg:
            c.pendencias.append(f"Proposta é da {c.proposta.seguradora}, mas está na pasta da {seg}")
    if len(acordos) == 1:
        c.acordo = acordos[0]
        c.escolha, cnpjs = acordo_mod.ler_acordo(acordos[0], tipos[acordos[0]])
        if c.proposta and c.proposta.cnpj and cnpjs and c.proposta.cnpj not in cnpjs:
            c.pendencias.append("O CNPJ citado no acordo é diferente do CNPJ da proposta")
        if ajuste and c.escolha:
            if ajuste.parcelas:
                c.escolha.parcelas, c.escolha.ambigua, c.escolha.origem = ajuste.parcelas, False, "consultor"
            if ajuste.forma:
                c.escolha.forma, c.escolha.forma_presumida = ajuste.forma, False

    return regras.aplicar(c, cfg)
