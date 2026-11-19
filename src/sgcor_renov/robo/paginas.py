"""Lógica do robô que não depende do navegador (testável sem o SGCOR):
URL de busca, leitura da lista de apólices, escolha da apólice a renovar e valores da 1ª tela.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlencode

from ..config import Config
from ..modelos import Caso
from ..numeros import formatar_cnpj, formatar_dinheiro, so_digitos

# ---------------------------------------------------------------- busca


def url_busca(cfg: Config, cnpj: str, seguradora: str, formatado: bool = True) -> str:
    """A pesquisa do SGCOR vai na URL: p = base64(formulário serializado)."""
    companhia = cfg.sgcor["companhia_porto" if seguradora == "PORTO" else "companhia_tokio"]
    campos = {
        "cpf_cnpj": formatar_cnpj(cnpj) if formatado else so_digitos(cnpj),
        "tipoCpfCnpj": "segurado",
        "companhiaId": companhia,
        "ramoId": cfg.sgcor["ramo_loterico"],
    }
    p = base64.b64encode(urlencode(campos).encode()).decode()
    return f"{cfg.url_sgcor}?op=propostas&form=listar&p={p}"


def url_renovar(cfg: Config, proposta_id: str) -> str:
    return f"{cfg.url_sgcor}?op=propostas&form=alterar&propostaId={proposta_id}&renovar=true"


def url_lista(cfg: Config) -> str:
    return f"{cfg.url_sgcor}?op=propostas&form=listar"


# ---------------------------------------------------------------- lista de apólices


@dataclass
class LinhaApolice:
    proposta_id: str
    apolice: str
    cliente: str
    cnpj: str            # só dígitos
    ramo: str
    companhia: str
    inicio: str          # dd/mm/aaaa
    fim: str
    tipo: str            # "Renovação" | "Nova" | ...
    status: str          # "Vigente" | "Renovada" | ...
    nivel: str = ""      # "Produção" (bolinha verde) | "Revisão" (bolinha amarela)


class _Tabela(HTMLParser):
    """Lê table#tabled_grid: por linha, (texto, title, títulos internos, onclicks) de cada <td>."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.dentro = False
        self.prof = 0
        self.linhas: list[list[dict]] = []
        self.td: dict | None = None
        self.tr: list[dict] | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table" and a.get("id") == "tabled_grid" and not self.dentro:
            self.dentro, self.prof = True, 0   # tabelas aninhadas com o mesmo id só aumentam a profundidade
        if not self.dentro:
            return
        if tag == "table":
            self.prof += 1
        elif tag == "tr" and self.prof == 1:
            if self.tr:                 # linha anterior sem </tr>: guarda antes de começar a nova
                self.linhas.append(self.tr)
            self.tr = []
        elif tag == "td" and self.prof == 1 and self.tr is not None:
            self.td = {"texto": "", "title": a.get("title") or "", "titulos": [], "onclick": [], "href": []}
            self.tr.append(self.td)
        elif self.td is not None:      # inclusive o conteúdo de tabelas aninhadas: fica na célula externa
            if a.get("title"):
                self.td["titulos"].append(a["title"])
            if a.get("onclick"):
                self.td["onclick"].append(a["onclick"])
            if tag == "a" and a.get("href"):
                self.td["href"].append(a["href"])

    def handle_endtag(self, tag):
        if not self.dentro:
            return
        if tag == "td" and self.prof == 1:
            self.td = None
        elif tag == "tr" and self.prof == 1 and self.tr is not None:
            if self.tr:
                self.linhas.append(self.tr)
            self.tr = None
        elif tag == "table":
            self.prof -= 1
            if self.prof == 0:
                self.dentro = False

    def handle_data(self, data):
        if self.td is not None:
            self.td["texto"] += data


def _titulo_com(tds: list[dict], prefixo: str) -> str:
    for td in tds:
        for t in [td["title"], *td["titulos"]]:
            if t.strip().startswith(prefixo):
                return t.strip()
    return ""


def ler_lista(html: str) -> list[LinhaApolice]:
    """Linhas da lista de Propostas/Apólices. Usa os títulos (tooltips) das células, mais estáveis que a posição."""
    p = _Tabela()
    p.feed(html)
    out = []
    for tds in p.linhas:
        renovar = next((oc for td in tds for oc in td["onclick"] if "renovar=true" in oc), "")
        m = re.search(r"propostaId=(\d+)", renovar)
        if not m:
            continue
        datas = [td["texto"].strip() for td in tds if re.fullmatch(r"\d{2}/\d{2}/\d{4}", td["texto"].strip())]
        cliente_t = _titulo_com(tds, "Tipo: Segurado")
        cnpj = re.search(r"CPF/CNPJ:\s*([\d./-]+)", cliente_t)
        nome = re.search(r"Nome:\s*(.*?)\s*CPF/CNPJ", cliente_t)
        apolice_t = _titulo_com(tds, "Pesquisar pela apólice")
        ap = re.search(r"Apólice:\s*(\S+)", apolice_t)
        ramo = re.search(r"Ramo:\s*(.*?)\s*Endereço", _titulo_com(tds, "Ramo:") + " Endereço")
        cia = next((t.strip() for td in tds for t in td["titulos"]
                    if re.search(r"PORTO|TOKIO|SEGURADORA|SEGUROS", t, re.I) and ":" not in t), "")
        tipo_t = next((t for td in tds for t in td["titulos"] if re.match(r"(Renovação|Nova|Endosso)\b", t.strip())), "")
        status = next((t.strip() for td in tds for t in td["titulos"]
                       if t.strip() in ("Vigente", "Renovada", "Recusada", "Cancelada", "Não Renovada", "Endossada",
                                        "Não Renovável")), "")
        nivel_t = " ".join(t for td in tds for t in [td["title"], *td["titulos"]] if re.search(r"N[íi]vel", t))
        nivel = "Revisão" if re.search(r"revis", nivel_t, re.I) else "Produção" if re.search(r"produ", nivel_t, re.I) \
            else ""
        out.append(LinhaApolice(
            proposta_id=m.group(1),
            apolice=ap.group(1) if ap else "",
            cliente=unescape(nome.group(1)) if nome else "",
            cnpj=so_digitos(cnpj.group(1)) if cnpj else "",
            ramo=ramo.group(1).strip() if ramo else "",
            companhia=cia,
            inicio=datas[0] if len(datas) > 0 else "",
            fim=datas[1] if len(datas) > 1 else "",
            tipo=tipo_t.split()[0] if tipo_t else "",
            status=status,
            nivel=nivel,
        ))
    return out


def _data(s: str) -> date:
    d, m, a = (int(x) for x in s.split("/"))
    return date(a, m, d)


def escolher_apolice(linhas: list[LinhaApolice], caso: Caso, cfg: Config) -> tuple[LinhaApolice | None, str | None]:
    """Q11/Q24/Q30/Q54: filtra CNPJ + companhia + ramo lotérico, descarta Nível Revisão e pega a de vigência
    mais recente. Devolve (linha, None) ou (None, motivo da pendência)."""
    cnpj = caso.proposta.cnpj if caso.proposta else None
    marca = "PORTO" if caso.seguradora == "PORTO" else "TOKIO"
    cand = [l for l in linhas
            if (not cnpj or l.cnpj == cnpj) and marca in l.companhia.upper() and "LOTÉRICO" in l.ramo.upper()
            and l.fim]
    if not cand:
        return None, "Nenhuma apólice lotérica desta seguradora encontrada no SGCOR para o CNPJ"
    # Q54: só vale o registro em Produção (bolinha verde); Revisão (bolinha amarela) é desconsiderado
    producao = [l for l in cand if l.nivel == "Produção"]
    if not producao:
        return None, "Nenhuma apólice em Nível Produção para o CNPJ (só em Revisão) — conferir no SGCOR"
    cand = producao
    cand.sort(key=lambda l: _data(l.fim), reverse=True)
    topo = cand[0]
    if len(cand) > 1 and cand[1].fim == topo.fim:
        return None, f"Mais de uma apólice com a mesma vigência final ({topo.fim}) — conferir no SGCOR"
    if topo.inicio == cfg.vigencia_inicio or topo.status == "Renovada":
        return None, (f"A renovação parece já cadastrada no SGCOR (ID {topo.proposta_id}, vigência "
                      f"{topo.inicio} a {topo.fim}, {topo.status or topo.tipo}) — conferir (Q30)")
    # Q55: a apólice a renovar é a que termina quando a nova começa (sem comparar nº: muitas têm 123456)
    if topo.fim != cfg.vigencia_inicio:
        return None, (f"A apólice mais recente em Produção (ID {topo.proposta_id}) termina em {topo.fim}, "
                      f"não em {cfg.vigencia_inicio} — conferir no SGCOR")
    return topo, None


# ---------------------------------------------------------------- 1ª tela (Q52)


@dataclass
class Campo:
    rotulo: str
    seletor: str
    valor: str
    tipo: str = "texto"     # texto | select | checkbox


def campos_primeira_tela(caso: Caso, cfg: Config, hoje: date | None = None) -> list[Campo]:
    """Exatamente os campos marcados pelo consultor; o resto fica como o SGCOR trouxe."""
    p = caso.proposta
    hoje = hoje or date.today()
    return [
        Campo("Proposta", "input[name='proposta']", p.numero or ""),
        Campo("Apólice", "#numeroApolice", cfg.apolice_provisoria),
        Campo("Apólice (Baixa comissão)", "input[name='apoliceBaixaComissao']", cfg.apolice_provisoria),
        Campo("Vigência início", "#data_texto_dataVigenciaInicial", cfg.vigencia_inicio),
        Campo("Vigência fim", "#data_texto_dataVigenciaFinal", cfg.vigencia_fim),
        Campo("Confirma as datas de vigência?", "#verificaConfirmacaoVigencia", "sim", "checkbox"),
        Campo("Comissão", "#comissao", f"{p.comissao},00"),
        Campo("Prêmio Total", "#premioTotal", formatar_dinheiro(caso.premio_total)),
        Campo("IOF", "#imposto", formatar_dinheiro(caso.iof)),
        Campo("Prêmio Líquido", "#premioLiquido", formatar_dinheiro(caso.premio_liquido)),
        Campo("Forma de Cobrança", "#cobrancaId", str(caso.cobranca_id), "select"),
        Campo("Parcelas", "#parcelas", str(caso.parcelas)),
        Campo("1ª Parcela – Vencimento", "#data_texto_dataEntrada", cfg.primeira_parcela),
        Campo("Emitida", "#data_texto_dataEmitida", hoje.strftime("%d/%m/%Y")),
    ]


def normalizar_valor(v: str) -> str:
    """Para comparar o que foi digitado com o que ficou no campo (máscaras podem mudar espaços)."""
    return re.sub(r"\s+", "", v or "")


# ---------------------------------------------------------------- F3: telas depois do Avançar

_DIN = re.compile(r"^\d{1,3}(?:\.\d{3})*,\d{2}$")


def _dec(txt: str) -> Decimal:
    return Decimal(txt.strip().replace(".", "").replace(",", "."))


def _linhas_tabela(html: str) -> list[list[dict]]:
    p = _Tabela()
    p.feed(html)
    return p.linhas


def itens_da_proposta(html: str, proposta_id: str) -> list[str]:
    """IDs dos itens (guarda-chuva) na tela de Itens e Coberturas."""
    return sorted(set(re.findall(rf"propostasItensCoberturas&(?:amp;)?form=listar&(?:amp;)?propostaId={proposta_id}"
                                 rf"&(?:amp;)?propostaItemId=(\d+)", html)))


@dataclass
class CoberturaSgcor:
    nome: str
    lmi: Decimal
    url_alterar: str


def ler_coberturas_item(html: str) -> list[CoberturaSgcor]:
    """Popup 'Coberturas Item > Lista': link Alterar, nome (título completo) e Valor/LMI (R$)."""
    out = []
    for tds in _linhas_tabela(html):
        url = next((unescape(h) for td in tds for h in td["href"] if "propostasItensCoberturas" in h
                    and "form=alterar" in h), "")
        if not url:
            continue
        nome = next((t for td in tds if not td["href"] and td["texto"].strip()
                     for t in [td["title"], *td["titulos"]] if t.strip() and t.strip() != "Alterar"), "")
        textos = [td["texto"].strip() for td in tds]
        if not nome:   # sem título: a célula de texto mais longa é o nome
            nome = max((t for t in textos if not _DIN.match(t) and not t.isdigit()), key=len, default="")
        i_nome = next((i for i, t in enumerate(textos) if t and nome.startswith(t.rstrip(". …"))), None)
        lmi = next((_dec(t) for t in textos[(i_nome or 0) + 1:] if _DIN.match(t)), None)
        if lmi is not None:
            out.append(CoberturaSgcor(nome.strip(), lmi, url))
    return out


@dataclass
class Ajuste:
    nome_sgcor: str
    de: Decimal
    para: Decimal
    url_alterar: str


def plano_coberturas(proposta: list[tuple], sgcor: list[CoberturaSgcor], dic) -> tuple[list[Ajuste], list[str]]:
    """Q8/Q51: casa por tipo (dicionário). Devolve (ajustes de LMI a fazer, pendências).
    proposta = [(Cobertura, chave)] já classificada na F1."""
    pend: list[str] = []
    por_tipo: dict[str, list[CoberturaSgcor]] = {}
    for c in sgcor:
        t = dic.tipo_de(c.nome, "sgcor")
        if t:
            por_tipo.setdefault(t.chave, []).append(c)
    ajustes: list[Ajuste] = []
    usados: set[int] = set()
    for cob, chave in proposta:
        if chave is None:
            pend.append(f"Cobertura da proposta sem equivalência: “{cob.nome}”")
            continue
        alvos = por_tipo.get(chave, [])
        if not alvos:
            pend.append(f"Cobertura nova na proposta (não existe no item do SGCOR): “{cob.nome}” R$ {cob.lmi}")
        elif len(alvos) > 1:
            pend.append(f"Mais de uma cobertura do mesmo tipo no item do SGCOR para “{cob.nome}”: "
                        + "; ".join(a.nome for a in alvos))
        else:
            alvo = alvos[0]
            usados.add(id(alvo))
            if alvo.lmi != cob.lmi:
                ajustes.append(Ajuste(alvo.nome, alvo.lmi, cob.lmi, alvo.url_alterar))
    for c in sgcor:   # Q51: cobertura do item sem par na proposta → LMI 0 ignora; LMI > 0 pendência
        if id(c) not in usados and c.lmi > 0:
            pend.append(f"Cobertura do item do SGCOR não está na proposta nova (LMI R$ {c.lmi}): “{c.nome}”")
    return ajustes, pend


def url_editar_repasse(html: str) -> list[str]:
    """Links do lápis da lista de repasses (vêm dentro de confirmaSwal(...))."""
    urls = re.findall(r"(\?op=repasses&(?:amp;)?form=alterar&(?:amp;)?propostaRepasseId=\d+[^'\"]*)", html)
    return sorted({unescape(u) for u in urls})


@dataclass
class Parcela:
    numero: int
    valor: Decimal
    vencimento: str


def ler_parcelas(html: str) -> list[Parcela]:
    out = []
    for tds in _linhas_tabela(html):
        textos = [re.sub(r"\s+", " ", td["texto"]).strip() for td in tds]
        i_data = next((i for i, t in enumerate(textos) if re.fullmatch(r"\d{2}/\d{2}/\d{4}", t)), None)
        if i_data is None:
            continue
        valor = next((_dec(t) for t in reversed(textos[:i_data]) if _DIN.match(t)), None)
        numero = next((int(t) for t in textos[:i_data] if t.isdigit()), None)
        if valor is not None and numero is not None:
            out.append(Parcela(numero, valor, textos[i_data]))
    return out


def conferir_parcelas(parcelas: list[Parcela], caso: Caso, cfg: Config) -> list[str]:
    """Só confere o que o SGCOR gerou (nunca apaga/recadastra)."""
    erros = []
    if len(parcelas) != caso.parcelas:
        erros.append(f"SGCOR gerou {len(parcelas)} parcela(s); o combinado são {caso.parcelas}")
    if parcelas and min(parcelas, key=lambda p: p.numero).vencimento != cfg.primeira_parcela:
        erros.append(f"1º vencimento {min(parcelas, key=lambda p: p.numero).vencimento} ≠ {cfg.primeira_parcela}")
    soma = sum((p.valor for p in parcelas), Decimal(0))
    if caso.premio_total is not None and abs(soma - caso.premio_total) > Decimal("0.10"):
        erros.append(f"Soma das parcelas R$ {soma} ≠ prêmio total R$ {caso.premio_total}")
    return erros


def anexos_existentes(html: str) -> set[str]:
    """Descrições já anexadas (para não reenviar)."""
    descr = set()
    for tds in _linhas_tabela(html):
        if any("anexos" in h and "form=alterar" in h for td in tds for h in td["href"]):
            for td in tds:
                t = td["texto"].strip().upper()
                if t in ("ACORDO", "PROPOSTA"):
                    descr.add(t)
    return descr
