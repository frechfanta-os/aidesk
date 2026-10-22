"""Tests F-2/B9 — ligne de porte dans le rapport hebdo (CLI réel, DB tmp)."""
from __future__ import annotations

import subprocess
import sqlite3
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent


def seed_db(tmp_path, n_op: int, n_off: int = 7) -> Path:
    db = tmp_path / "aidesk.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
      CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_open REAL, ts_close REAL, symbol TEXT, entry REAL, exit REAL, qty REAL,
        pnl REAL, reason TEXT, agent TEXT, approver TEXT, score REAL,
        features TEXT, mode TEXT DEFAULT 'unknown');
      CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL,
        kind TEXT, payload TEXT);
      CREATE TABLE decisions (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL,
        symbol TEXT, agent TEXT, agg REAL, verdict INTEGER, thesis TEXT,
        objection TEXT, scores TEXT);
      CREATE TABLE matrix_history (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL,
        revision INTEGER, note TEXT);
    """)
    conn.execute("INSERT INTO events (ts,kind,payload) VALUES (?,?,?)",
                 (time.time(), "boot", '{"start_usdt": 30.0}'))
    for i in range(n_op):
        conn.execute("INSERT INTO trades (ts_close,pnl,reason,mode) VALUES (?,?,?,?)",
                     (time.time(), 0.2 if i % 2 == 0 else -0.1, "TP", "live"))
    for i in range(n_off):
        conn.execute("INSERT INTO trades (ts_close,pnl,reason,mode) VALUES (?,?,?,?)",
                     (time.time(), 0.0, "TP", "offline"))
    conn.commit()
    conn.close()
    return db


def run_report(db: Path) -> str:
    out = subprocess.run(
        [sys.executable, str(PROJECT / "tools" / "report_week.py"),
         "--db", str(db), "--days", "30"],
        capture_output=True, text=True, check=True, cwd=str(PROJECT))
    return out.stdout


def test_sous_la_porte_non_qualifie(tmp_path):
    txt = run_report(seed_db(tmp_path, 29))
    assert "porte Go/No-Go : **29/30** opérationnels — NON-QUALIFIÉ" in txt
    assert "IC95 %" in txt and "__" not in txt.splitlines()[5]


def test_porte_atteinte_descriptif(tmp_path):
    txt = run_report(seed_db(tmp_path, 37))
    assert "porte Go/No-Go : **37/30** opérationnels" in txt   # compte brut honest
    assert "ATTEINTE" in txt and "NON-QUALIFIÉ" not in txt


def test_ci_sans_trade_zero_division(tmp_path):
    txt = run_report(seed_db(tmp_path, 0, n_off=3))
    assert "winrate" not in txt or "- trades clôturés : **0**" in txt
