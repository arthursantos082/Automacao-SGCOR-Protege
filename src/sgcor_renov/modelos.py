"""Estruturas de dados compartilhadas."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path


@dataclass
class OpcaoPagamento:
    forma: str            # boleto | cartao | cartao_porto | debito_pix | debito
    parcelas: int         # total de parcelas (A+B somado)
    primeira: Decimal
    demais: Decimal
    premio_total: Decimal | None = None
    iof: Decimal | None = None
    premio_liquido: Decimal | None = None  # Porto: muda com a forma (à vista / cartão Porto têm desconto)
    marcada: bool = False  # "(X)" na proposta Tokio — só informativo
    descricao: str = ""


@dataclass
class Proposta:
    seguradora: str                 # PORTO | TOKIO
    numero: str | None = None       # Cotação nº / Nº do orçamento → campo "Proposta" no SGCOR
    apolice_anterior: str | None = None
    cnpj: str | None = None         # só dígitos
    razao_social: str | None = None
    vigencia_inicio: str | None = None
    vigencia_fim: str | None = None
    premio_liquido: Decimal | None = None
    iof: Decimal | None = None
    premio_total: Decimal | None = None
    comissao: int | None = None
    opcoes: list[OpcaoPagamento] = field(default_factory=list)
    problemas: list[str] = field(default_factory=list)


@dataclass
class Escolha:
    parcelas: int | None = None
    forma: str | None = None        # boleto | cartao | cartao_porto | pix | debito
    trecho_parcelas: str = ""
    trecho_forma: str = ""
    ambigua: bool = False
    mensagens_cliente: int = 0
    origem: str = ""                # "cliente" | "oferta aceita"
    forma_presumida: bool = False   # ninguém citou a forma → boleto (Q32)


@dataclass
class Caso:
    seguradora: str
    pasta: Path
    nome: str
    acordo: Path | None = None
    propostas: list[Path] = field(default_factory=list)
    proposta_escolhida: Path | None = None
    proposta: Proposta | None = None
    escolha: Escolha | None = None
    parcelas: int | None = None
    forma: str | None = None
    cobranca_id: int | None = None
    premio_liquido: Decimal | None = None
    iof: Decimal | None = None
    premio_total: Decimal | None = None
    bonus: Decimal | None = None
    coberturas: list = field(default_factory=list)   # [(Cobertura, chave do tipo | None)]
    pendencias: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "Pendente" if self.pendencias else "Pronto"
