"""Varre as pastas FECHADOS PORTO / FECHADOS TOKIO e monta um Caso por lotérica."""
from __future__ import annotations

from pathlib import Path

from . import acordo as acordo_mod
from . import coberturas as cob_mod
from . import propostas as prop_mod
from . import regras
from .config import Config
from .modelos import Caso
from .numeros import formatar_cnpj, separar_cnpj
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


_DIC: cob_mod.Dicionario | None = None


def _coberturas(c: Caso, proposta: Path, ajustar: tuple[str, ...]) -> None:
    """Lê coberturas + LMI e classifica pelo dicionário (Q59). Só os tipos em `ajustar` (Incêndio, Valores no
    interior/em trânsito) importam: tipo desses repetido → pendência; o resto, no máximo, vira aviso."""
    global _DIC
    _DIC = _DIC or cob_mod.Dicionario.carregar()
    origem = c.proposta.seguradora.lower()
    cobs = cob_mod.ler(proposta, c.proposta.seguradora)
    if not cobs:
        c.pendencias.append("Coberturas da proposta não encontradas")
        return
    vistos: dict[str, str] = {}
    for cob in cobs:
        t = _DIC.tipo_de(cob.nome, origem)
        c.coberturas.append((cob, t.chave if t else None))
        if t is None or t.chave not in ajustar:
            continue                                   # fica como veio no SGCOR
        if t.chave in vistos:
            c.pendencias.append(f"Duas coberturas do mesmo tipo ({t.descricao}): “{vistos[t.chave]}” e “{cob.nome}”")
        else:
            vistos[t.chave] = cob.nome


def analisar_pasta(pasta: Path, seg: str, cfg: Config, ajuste=None) -> Caso:
    # Q72: a pasta pode ter o nome da lotérica, o nome + CNPJ, ou só o CNPJ
    nome, cnpj_pasta = separar_cnpj(pasta.name)
    c = Caso(seguradora=seg, pasta=pasta, nome=nome or pasta.name)
    pdfs = sorted(pasta.glob("*.pdf"))
    tipos: dict[Path, str] = {}
    textos: dict[Path, str] = {}
    for pdf in pdfs:
        try:
            textos[pdf] = texto(pdf)
        except Exception as e:  # PDF corrompido/protegido: se for o acordo ou a cotação, a falta deles vira pendência
            c.avisos.append(f"PDF ignorado (não foi possível ler): {pdf.name} — {e}")
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

    # Q69: a pasta pode trazer outros PDFs (ex.: a apólice anterior); o robô só usa a cotação e o acordo
    for o in outros:
        c.avisos.append(f"PDF ignorado (não é cotação nem acordo): {o.name}")
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
    c.proposta_escolhida = escolhida

    if escolhida:
        c.proposta = prop_mod.ler_proposta(textos[escolhida])
        if c.proposta.seguradora != seg:
            c.pendencias.append(f"Proposta é da {c.proposta.seguradora}, mas está na pasta da {seg}")
        if cnpj_pasta and c.proposta.cnpj and cnpj_pasta != c.proposta.cnpj:
            c.pendencias.append(f"O CNPJ no nome da pasta ({formatar_cnpj(cnpj_pasta)}) é diferente do CNPJ da "
                                f"proposta ({formatar_cnpj(c.proposta.cnpj)})")
        if not nome and c.proposta.razao_social:      # pasta só com o CNPJ: mostra o nome da proposta
            c.nome = c.proposta.razao_social
        _coberturas(c, escolhida, cfg.coberturas_ajustar)
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

    if ajuste:
        c.vigencia_confirmada = ajuste.vigencia
        c.sem_apolice_confirmado = ajuste.sem_apolice
    return regras.aplicar(c, cfg)


# ---------------------------------------------------------------- Q75: evitar cadastrar de novo


def cnpj_da_pasta(pasta: Path) -> str | None:
    """CNPJ de uma pasta (ex.: em _CADASTRADOS): o do nome da pasta, senão o da proposta que está nela."""
    _, cnpj = separar_cnpj(pasta.name)
    if cnpj:
        return cnpj
    # o acordo é o PDF mais demorado de ler: tenta antes os outros (a proposta quase nunca começa com "ACORDO")
    for pdf in sorted(pasta.glob("*.pdf"), key=lambda p: (p.name.upper().startswith("ACORDO"), p.name)):
        try:
            t = texto(pdf, max_paginas=2)          # o CNPJ do segurado está no começo da proposta
            if prop_mod.classificar(t).startswith("PROPOSTA"):
                cnpj = prop_mod.ler_proposta(t).cnpj
                if cnpj:
                    return cnpj
        except Exception:
            continue
    return None


def _nome_comparavel(nome_pasta: str) -> str:
    import re
    import unicodedata
    nome, _ = separar_cnpj(re.sub(r"\s*\(\d{8}-\d{6}\)$", "", nome_pasta))   # tira o "(20261119-101500)" do mover
    nome = unicodedata.normalize("NFKD", nome.upper()).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", " ", nome).strip()


def marcar_ja_cadastradas(casos: list[Caso], cadastradas: dict[Path, str | None]) -> list[Caso]:
    """Q75: lotérica que já está em _CADASTRADOS (mesmo CNPJ, ou mesmo nome de pasta) e voltou para FECHADOS →
    pendência, para não cadastrar duas vezes. Devolve cópias (os casos do cache não são alterados)."""
    import copy
    por_cnpj: dict[str, Path] = {}
    por_nome: dict[str, Path] = {}
    for p, cnpj in cadastradas.items():
        if cnpj:
            por_cnpj.setdefault(cnpj, p)
        if n := _nome_comparavel(p.name):
            por_nome.setdefault(n, p)
    out = []
    for c in casos:
        cnpj = (c.proposta.cnpj if c.proposta else None) or separar_cnpj(c.pasta.name)[1]
        achou = (por_cnpj.get(cnpj) if cnpj else None) or por_nome.get(_nome_comparavel(c.pasta.name))
        if achou:
            c = copy.copy(c)
            c.pendencias = c.pendencias + [f"Já cadastrada: esta lotérica já está em {achou.parent.parent.name} › "
                                           f"_CADASTRADOS › “{achou.name}” — não cadastrar de novo"]
        out.append(c)
    return out
