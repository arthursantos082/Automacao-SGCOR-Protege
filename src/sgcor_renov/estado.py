"""Estado local (SQLite) fora do repositório: ajustes feitos pelo consultor no app.

Fica em %LOCALAPPDATA%\\SGCOR-Renovacoes\\estado.sqlite (nunca no git — tem dados de clientes).
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path


def pasta_dados() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    p = base / "SGCOR-Renovacoes"
    p.mkdir(parents=True, exist_ok=True)
    return p


@dataclass
class Ajuste:
    """O que o consultor informou para resolver pendências de uma pasta."""
    parcelas: int | None = None
    forma: str | None = None
    proposta: str | None = None   # nome do arquivo escolhido quando há 2+ propostas
    vigencia: str | None = None   # Q64: início da proposta que o consultor aceitou trocar pela vigência padrão
    sem_apolice: bool = False     # Q68: o consultor aceitou seguir sem o nº da apólice anterior
    cnpj_confirmado: str | None = None   # Q80: CNPJ da proposta confirmado apesar de o acordo citar outro CNPJ
    vigencia_alterada: str | None = None # Q83: "dd/mm/aaaa a dd/mm/aaaa" escolhida pelo consultor (no lugar da padrão)

    def vazio(self) -> bool:
        return (self.parcelas is None and self.forma is None and self.proposta is None and self.vigencia is None
                and not self.sem_apolice and self.cnpj_confirmado is None and self.vigencia_alterada is None)


class Estado:
    def __init__(self, caminho: Path | None = None):
        self.caminho = caminho or pasta_dados() / "estado.sqlite"
        self.db = sqlite3.connect(self.caminho, timeout=10)   # tela e robô abrem conexões próprias
        self.db.execute("""CREATE TABLE IF NOT EXISTS ajustes (
            pasta TEXT PRIMARY KEY, parcelas INTEGER, forma TEXT, proposta TEXT,
            atualizado TEXT DEFAULT CURRENT_TIMESTAMP)""")
        colunas = {r[1] for r in self.db.execute("PRAGMA table_info(ajustes)")}   # estado de versões anteriores
        if "vigencia" not in colunas:
            self.db.execute("ALTER TABLE ajustes ADD COLUMN vigencia TEXT")
        if "sem_apolice" not in colunas:
            self.db.execute("ALTER TABLE ajustes ADD COLUMN sem_apolice INTEGER DEFAULT 0")
        if "cnpj_confirmado" not in colunas:
            self.db.execute("ALTER TABLE ajustes ADD COLUMN cnpj_confirmado TEXT")
        if "vigencia_alterada" not in colunas:
            self.db.execute("ALTER TABLE ajustes ADD COLUMN vigencia_alterada TEXT")
        # renovação criada no SGCOR (depois do Avançar) que ficou pela metade: o robô retoma da etapa
        self.db.execute("""CREATE TABLE IF NOT EXISTS renovacoes_pela_metade (
            pasta TEXT PRIMARY KEY, proposta_id TEXT NOT NULL, etapa TEXT NOT NULL, motivo TEXT,
            atualizado TEXT DEFAULT CURRENT_TIMESTAMP)""")
        # lotéricas que o robô terminou (chave = pasta já dentro de _CADASTRADOS)
        self.db.execute("""CREATE TABLE IF NOT EXISTS cadastradas (
            pasta TEXT PRIMARY KEY, nome TEXT, seguradora TEXT, proposta_id TEXT, produtor TEXT,
            quando TEXT DEFAULT (datetime('now', 'localtime')))""")
        self.db.commit()

    def registrar_cadastrada(self, pasta: Path, nome: str, seguradora: str, proposta_id: str, produtor: str,
                             quando: str | None = None) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO cadastradas (pasta, nome, seguradora, proposta_id, produtor, quando) "
            "VALUES (?, ?, ?, ?, ?, COALESCE(?, datetime('now', 'localtime')))",
            (str(pasta), nome, seguradora, proposta_id, produtor, quando))
        self.db.commit()

    def cadastradas(self) -> dict[str, dict]:
        """pasta → {nome, seguradora, proposta_id, produtor, quando}."""
        cur = self.db.execute("SELECT pasta, nome, seguradora, proposta_id, produtor, quando FROM cadastradas")
        return {r[0]: dict(zip(("nome", "seguradora", "proposta_id", "produtor", "quando"), r[1:])) for r in cur}

    def pela_metade(self, pasta: Path) -> tuple[str, str] | None:
        row = self.db.execute("SELECT proposta_id, etapa FROM renovacoes_pela_metade WHERE pasta = ?",
                              (str(pasta),)).fetchone()
        return (row[0], row[1]) if row else None

    def pela_metade_detalhe(self, pasta: Path) -> tuple[str, str, str] | None:
        """(ID da renovação no SGCOR, etapa em que parou, motivo) — para mostrar nas Pendências (Q76)."""
        row = self.db.execute("SELECT proposta_id, etapa, motivo FROM renovacoes_pela_metade WHERE pasta = ?",
                              (str(pasta),)).fetchone()
        return (row[0], row[1], row[2] or "") if row else None

    def marcar_pela_metade(self, pasta: Path, proposta_id: str, etapa: str, motivo: str) -> None:
        self.db.execute(
            "INSERT INTO renovacoes_pela_metade (pasta, proposta_id, etapa, motivo) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(pasta) DO UPDATE SET proposta_id=excluded.proposta_id, etapa=excluded.etapa, "
            "motivo=excluded.motivo, atualizado=CURRENT_TIMESTAMP", (str(pasta), proposta_id, etapa, motivo))
        self.db.commit()

    def limpar_pela_metade(self, pasta: Path) -> None:
        self.db.execute("DELETE FROM renovacoes_pela_metade WHERE pasta = ?", (str(pasta),))
        self.db.commit()

    def ajuste(self, pasta: Path) -> Ajuste | None:
        row = self.db.execute("SELECT parcelas, forma, proposta, vigencia, sem_apolice, cnpj_confirmado, "
                              "vigencia_alterada FROM ajustes WHERE pasta = ?", (str(pasta),)).fetchone()
        return Ajuste(*row[:4], bool(row[4]), row[5], row[6]) if row else None

    def salvar(self, pasta: Path, a: Ajuste) -> None:
        if a.vazio():
            self.db.execute("DELETE FROM ajustes WHERE pasta = ?", (str(pasta),))
        else:
            self.db.execute(
                "INSERT INTO ajustes (pasta, parcelas, forma, proposta, vigencia, sem_apolice, cnpj_confirmado, "
                "vigencia_alterada) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(pasta) DO UPDATE SET parcelas=excluded.parcelas, forma=excluded.forma, "
                "proposta=excluded.proposta, vigencia=excluded.vigencia, sem_apolice=excluded.sem_apolice, "
                "cnpj_confirmado=excluded.cnpj_confirmado, vigencia_alterada=excluded.vigencia_alterada, "
                "atualizado=CURRENT_TIMESTAMP",
                (str(pasta), a.parcelas, a.forma, a.proposta, a.vigencia, int(a.sem_apolice), a.cnpj_confirmado,
                 a.vigencia_alterada))
        self.db.commit()

    def fechar(self) -> None:
        self.db.close()
