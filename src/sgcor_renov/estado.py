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

    def vazio(self) -> bool:
        return self.parcelas is None and self.forma is None and self.proposta is None


class Estado:
    def __init__(self, caminho: Path | None = None):
        self.caminho = caminho or pasta_dados() / "estado.sqlite"
        self.db = sqlite3.connect(self.caminho, timeout=10)   # tela e robô abrem conexões próprias
        self.db.execute("""CREATE TABLE IF NOT EXISTS ajustes (
            pasta TEXT PRIMARY KEY, parcelas INTEGER, forma TEXT, proposta TEXT,
            atualizado TEXT DEFAULT CURRENT_TIMESTAMP)""")
        # renovação criada no SGCOR (depois do Avançar) que ficou pela metade: o robô retoma da etapa
        self.db.execute("""CREATE TABLE IF NOT EXISTS renovacoes_pela_metade (
            pasta TEXT PRIMARY KEY, proposta_id TEXT NOT NULL, etapa TEXT NOT NULL, motivo TEXT,
            atualizado TEXT DEFAULT CURRENT_TIMESTAMP)""")
        self.db.commit()

    def pela_metade(self, pasta: Path) -> tuple[str, str] | None:
        row = self.db.execute("SELECT proposta_id, etapa FROM renovacoes_pela_metade WHERE pasta = ?",
                              (str(pasta),)).fetchone()
        return (row[0], row[1]) if row else None

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
        row = self.db.execute("SELECT parcelas, forma, proposta FROM ajustes WHERE pasta = ?",
                              (str(pasta),)).fetchone()
        return Ajuste(*row) if row else None

    def salvar(self, pasta: Path, a: Ajuste) -> None:
        if a.vazio():
            self.db.execute("DELETE FROM ajustes WHERE pasta = ?", (str(pasta),))
        else:
            self.db.execute(
                "INSERT INTO ajustes (pasta, parcelas, forma, proposta) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(pasta) DO UPDATE SET parcelas=excluded.parcelas, forma=excluded.forma, "
                "proposta=excluded.proposta, atualizado=CURRENT_TIMESTAMP",
                (str(pasta), a.parcelas, a.forma, a.proposta))
        self.db.commit()

    def fechar(self) -> None:
        self.db.close()
