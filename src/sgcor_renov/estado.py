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
        self.db = sqlite3.connect(self.caminho)
        self.db.execute("""CREATE TABLE IF NOT EXISTS ajustes (
            pasta TEXT PRIMARY KEY, parcelas INTEGER, forma TEXT, proposta TEXT,
            atualizado TEXT DEFAULT CURRENT_TIMESTAMP)""")
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
