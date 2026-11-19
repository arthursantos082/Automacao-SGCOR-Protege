"""Lógica do robô que não depende do navegador (testável sem o SGCOR):
URL de busca, leitura da lista de apólices, escolha da apólice a renovar e valores da 1ª tela.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from datetime import date
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
        if tag == "table" and a.get("id") == "tabled_grid":
            self.dentro, self.prof = True, 0
        if not self.dentro:
            return
        if tag == "table":
            self.prof += 1
        elif tag == "tr" and self.prof == 1:
            self.tr = []
        elif tag == "td" and self.tr is not None:
            self.td = {"texto": "", "title": a.get("title") or "", "titulos": [], "onclick": []}
            self.tr.append(self.td)
        elif self.td is not None:
            if a.get("title"):
                self.td["titulos"].append(a["title"])
            if a.get("onclick"):
                self.td["onclick"].append(a["onclick"])

    def handle_endtag(self, tag):
        if not self.dentro:
            return
        if tag == "td":
            self.td = None
        elif tag == "tr" and self.tr is not None:
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
        nivel_t = next((t.strip() for td in tds for t in td["titulos"] if re.match(r"N[íi]vel\s+\S", t.strip())), "")
        nivel = re.sub(r"^N[íi]vel\s+", "", nivel_t)
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
