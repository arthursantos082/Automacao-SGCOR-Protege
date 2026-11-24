"""Varre as pastas FECHADOS PORTO / FECHADOS TOKIO e monta um Caso por lotérica."""
from __future__ import annotations

import unicodedata
from pathlib import Path

from . import acordo as acordo_mod
from . import coberturas as cob_mod
from . import propostas as prop_mod
from . import regras
from .config import Config
from .modelos import PEND_ACORDO_IMAGEM, PEND_PROPOSTA_IMAGEM, Caso, Escolha
from .numeros import formatar_cnpj, separar_cnpj
from .pdftexto import PdfImagem, paginas_uteis, texto

CADASTRADOS = "_CADASTRADOS"
IGNORAR = (CADASTRADOS,)
FOTOS = (".png", ".jpg", ".jpeg")   # Q88: acordo salvo como foto/print, fora de PDF


def _fotos(pasta: Path) -> list[Path]:
    return sorted(p for p in pasta.iterdir() if p.is_file() and p.suffix.lower() in FOTOS)


def dir_cadastrados(pasta_loterica: Path) -> Path:
    """Q85: para onde vai a lotérica cadastrada — _CADASTRADOS na pasta-mãe, ao lado de FECHADOS-PORTO e
    FECHADOS-TOKIO (uma só para as duas seguradoras)."""
    return pasta_loterica.parent.parent / CADASTRADOS


def pastas_cadastrados(raizes: list[Path]) -> list[Path]:
    """Q85: as pastas _CADASTRADOS que existem — a da pasta-mãe e as antigas, dentro de cada FECHADOS (de antes da
    1.1.8), para continuar vendo e conferindo as lotéricas que já estão nelas."""
    out: list[Path] = []
    for raiz in raizes:
        for d in (raiz.parent / CADASTRADOS, raiz / CADASTRADOS):
            if d not in out and d.is_dir():
                out.append(d)
    return out


def lotericas_cadastradas(raizes: list[Path]) -> list[Path]:
    """As pastas de lotérica dentro de todas as _CADASTRADOS."""
    return [p for d in pastas_cadastrados(raizes) for p in d.iterdir() if p.is_dir()]


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
    return tuple(sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in [*pasta.glob("*.pdf"), *_fotos(pasta)]))


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
    cobs = cob_mod.ler(proposta, c.proposta.seguradora, paginas_uteis(proposta))
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


# Q80: o acordo cita outro CNPJ (cliente com mais de uma lotérica) → o consultor confirma no app
PEND_CNPJ_ACORDO = "O CNPJ citado no acordo é diferente do CNPJ da proposta"


def analisar_pasta(pasta: Path, seg: str, cfg: Config, ajuste=None) -> Caso:
    # Q72: a pasta pode ter o nome da lotérica, o nome + CNPJ, ou só o CNPJ
    nome, cnpj_pasta = separar_cnpj(pasta.name)
    c = Caso(seguradora=seg, pasta=pasta, nome=nome or pasta.name)
    pdfs = sorted(pasta.glob("*.pdf"))
    tipos: dict[Path, str] = {}
    textos: dict[Path, str] = {}
    imagens: list[Path] = _fotos(pasta)    # PNG/JPG: o AutoCOR não lê, como o PDF só com imagem
    for pdf in pdfs:
        try:
            textos[pdf] = texto(pdf, so_uteis=True)   # Q88: sem as condições gerais / o resto da apólice
        except PdfImagem:                 # Q87: sem texto para ler (impresso em PDF, print de tela)
            imagens.append(pdf)
            continue
        except Exception as e:  # PDF corrompido/protegido: se for o acordo ou a cotação, a falta deles vira pendência
            c.avisos.append(f"PDF ignorado (não foi possível ler): {pdf.name} — {e}")
            continue
        tipos[pdf] = prop_mod.classificar(textos[pdf])

    acordos = [p for p, t in tipos.items() if t.startswith("ACORDO")]
    props = [p for p, t in tipos.items() if t.startswith("PROPOSTA")]
    outros = [p for p, t in tipos.items() if t == "DESCONHECIDO"]

    # um PDF que não é proposta, numa pasta com exatamente 1 proposta, é tratado como acordo (ex.: e-mail impresso)
    # — a não ser que haja uma imagem com "ACORDO" no nome (Q88: o outro PDF é a apólice)
    if not acordos and len(props) == 1 and len(outros) == 1 and not any("ACORDO" in _nome(p) for p in imagens):
        acordos, outros = outros, []
        tipos[acordos[0]] = "ACORDO_EMAIL"
        c.avisos.append(f"Acordo identificado por eliminação: {acordos[0].name}")

    acordo_img, proposta_img = _imagens(imagens, acordos, props)
    for p in imagens:
        if p not in (acordo_img, proposta_img):
            tipo = "PDF" if p.suffix.lower() == ".pdf" else "Arquivo"
            c.avisos.append(f"{tipo} ignorado (salvo como imagem, o AutoCOR não lê): {p.name}")

    # Q69: a pasta pode trazer outros PDFs (ex.: a apólice anterior); o robô só usa a cotação e o acordo
    for o in outros:
        c.avisos.append(f"PDF ignorado (não é cotação nem acordo): {o.name}")
    if acordo_img:
        # Q87: o consultor lê o acordo e informa parcelas e forma no Resolver; até lá, pendência (laranja se for a única)
        c.acordo = acordo_img
        if ajuste and ajuste.parcelas and ajuste.forma:
            c.escolha = Escolha(ajuste.parcelas, ajuste.forma, origem="consultor")
            c.avisos.append(f"{PEND_ACORDO_IMAGEM} ({acordo_img.name}): parcelas e forma informadas pelo consultor")
        else:
            c.pendencias.append(f"{PEND_ACORDO_IMAGEM} (print/imagem): {acordo_img.name} — o AutoCOR não lê imagem; "
                                f"abra o acordo e informe as parcelas e a forma no Resolver")
    elif len(acordos) != 1:
        c.pendencias.append("Acordo não encontrado" if not acordos else f"{len(acordos)} acordos na pasta")
    c.propostas = props
    escolhida = None
    if len(props) == 1:
        escolhida = props[0]
    elif len(props) > 1 and ajuste and ajuste.proposta:
        escolhida = next((p for p in props if p.name == ajuste.proposta), None)
        if escolhida:
            c.avisos.append(f"Proposta final escolhida pelo consultor: {escolhida.name}")
    if proposta_img:
        c.propostas = [proposta_img]          # só para o "Abrir proposta" (fica amarelo pela pendência)
        c.pendencias.append(f"{PEND_PROPOSTA_IMAGEM} ({'impressa em PDF' if proposta_img.suffix.lower() == '.pdf' else 'foto/print'}): {proposta_img.name} — o AutoCOR não lê "
                            f"imagem; baixe o PDF original no portal da seguradora e troque na pasta")
    elif not props:
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
            citados = ", ".join(formatar_cnpj(x) for x in sorted(cnpjs))
            msg = f"{PEND_CNPJ_ACORDO} ({citados} × {formatar_cnpj(c.proposta.cnpj)})"
            if ajuste and ajuste.cnpj_confirmado == c.proposta.cnpj:
                # Q80: cliente com mais de uma lotérica — o consultor confirmou que o acordo vale para esta
                c.avisos.append(f"{msg}; o consultor confirmou a lotérica")
            else:
                c.pendencias.append(msg)
        if ajuste and c.escolha:
            if ajuste.parcelas:
                c.escolha.parcelas, c.escolha.ambigua, c.escolha.origem = ajuste.parcelas, False, "consultor"
            if ajuste.forma:
                c.escolha.forma, c.escolha.forma_presumida = ajuste.forma, False

    if ajuste:
        c.vigencia_confirmada = ajuste.vigencia
        c.sem_apolice_confirmado = ajuste.sem_apolice
        if ajuste.vigencia_alterada and " a " in ajuste.vigencia_alterada:
            ini, fim = ajuste.vigencia_alterada.split(" a ", 1)
            c.vigencia_alterada = (ini.strip(), fim.strip())
    return regras.aplicar(c, cfg)


def _nome(p: Path) -> str:
    """Nome do arquivo em maiúsculas e sem acento (para achar ACORDO/PROPOSTA/COTAÇÃO…)."""
    return unicodedata.normalize("NFKD", p.stem.upper()).encode("ascii", "ignore").decode()


def _imagens(imagens: list[Path], acordos: list[Path], props: list[Path]) -> tuple[Path | None, Path | None]:
    """Q87: entre os PDFs só com imagem, qual é o acordo e qual é a proposta — pelo nome do arquivo ("ACORDO",
    "PROPOSTA", "COTAÇÃO", "ORÇAMENTO", "ESTIMATIVA") ou por eliminação (a outra peça já está na pasta em texto)."""
    if not imagens:
        return None, None
    de_acordo = [p for p in imagens if "ACORDO" in _nome(p)]
    de_proposta = [p for p in imagens if p not in de_acordo
                   and any(k in _nome(p) for k in ("PROPOSTA", "COTACAO", "ORCAMENTO", "ESTIMATIVA"))]
    sem_nome = [p for p in imagens if p not in de_acordo and p not in de_proposta]
    acordo = proposta = None
    if not acordos:
        cand = de_acordo or (sem_nome if (props or de_proposta) else [])
        acordo = cand[0] if len(cand) == 1 else None
    if not props:
        cand = de_proposta or ([p for p in sem_nome if p != acordo] if (acordos or acordo) else [])
        proposta = cand[0] if len(cand) == 1 else None
    return acordo, proposta


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
                                           f"{achou.parent.name} › “{achou.name}” — não cadastrar de novo"]
        out.append(c)
    return out
