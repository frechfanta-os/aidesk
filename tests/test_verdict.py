"""Tests Phase F — porte de verdict statistique (bases synthétiques, pas la prod).

Contrats testés : porte mécanique ≥ 30 OPÉRATIONNELS, exclusions offline,
Wilson vraie numériquement, split chronologique 60/40, jamais d'affirmation
de rentabilité dans les messages.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from tools.verdict import PORTE, verdict, wilson, max_drawdown  # noqa: E402


def seed(tmp_path, op_pnls: list[float], offline_pnls: list[float] = ()) -> Path:
    conn = sqlite3.connect(str(tmp_path / "aidesk.db"))
    conn.executescript("""
      CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_open REAL, ts_close REAL, symbol TEXT, entry REAL, exit REAL,
        qty REAL, pnl REAL, reason TEXT, agent TEXT, approver TEXT,
        score REAL, features TEXT, mode TEXT DEFAULT 'unknown');
    """)
    for i, p in enumerate(op_pnls):
        conn.execute("INSERT INTO trades (ts_open,pnl,mode) VALUES (?,?,?)",
                     (1000.0 + i, p, "live"))
    for i, p in enumerate(offline_pnls):
        conn.execute("INSERT INTO trades (ts_open,pnl,mode) VALUES (?,?,?)",
                     (5000.0 + i, p, "offline"))
    conn.commit()
    conn.close()
    return tmp_path


def test_wilson_valeur_connue_et_bornes():
    # (k=16, n=30) → bornes connues à 1e-3 près (référence bibliographique)
    lo, hi = wilson(16, 30)
    assert abs(lo - 0.362) < 0.002 and abs(hi - 0.698) < 0.002
    lo1, hi1 = wilson(1, 10)
    assert abs(lo1 - 0.018) < 0.002 and abs(hi1 - 0.404) < 0.002
    assert wilson(0, 0) == (0.0, 1.0)


def test_max_drawdown_connu():
    assert abs(max_drawdown(30.0, [1.0, -0.5, 0.2]) - 0.5) < 1e-9
    assert max_drawdown(30.0, [1.0, 1.0]) == 0.0
    # équité 28, 29, 28 : le pic reste l'initial 30 (jamais revisité) → retrait 2.0
    assert abs(max_drawdown(30.0, [-2.0, 1.0, -1.0]) - 2.0) < 1e-9


def test_porte_non_atteinte_refuse_v_18(tmp_path):
    r = seed(tmp_path, [0.1] * 29)
    code, msgs = verdict(r)
    assert code == 1
    joined = "\n".join(msgs)
    assert "NON-QUALIFIÉ" in joined and "29/30" in joined
    assert "PORTE ATTEINTE" not in joined


def test_porte_atteinte_30_operationnels_exclut_offline(tmp_path):
    r = seed(tmp_path,
             [0.5, -0.4] * 15,                       # 30 opérationnels alternés
             [0.2] * 7)                              # 7 offline → exclus
    code, msgs = verdict(r)
    joined = "\n".join(msgs)
    assert code == 0
    assert "PORTE ATTEINTE (30/30)" in joined
    assert "7 offline EXCLUS" in joined
    assert "W/L 15/15" in joined
    assert "calibration" in joined and "validation" in joined
    # split 60/40 → 18 / 12
    assert "n=18" in joined and "n=12" in joined


def test_jamais_de_langage_rentable(tmp_path):
    """Anti-dérapage : même à la porte atteinte, aucun mot d'optimisme promis."""
    r = seed(tmp_path, [5.0] * PORTE)               # gain parfait impossible… mais
    _, msgs = verdict(r)                            # la sortie reste descriptif
    joined = " ".join(msgs).lower()
    # la négation « aucune garantie » (disclaimer) est autorisée ; ce qui est
    # interdit, ce sont les AFFIRMATIONS positives de rentabilité / garantie.
    for banned in ("rentable", "profitable", "rentabilité garantie",
                   "est garanti", "est rentable"):
        assert banned not in joined, banned


def test_db_absente_code_2(tmp_path):
    code, msgs = verdict(tmp_path)
    assert code == 2 and "absent" in msgs[0]
