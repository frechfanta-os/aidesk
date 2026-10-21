"""Tests B5 — provenance de session (live/offline) et isolation des stats.

Migration additive uniquement (ADD COLUMN mode), jamais de réécriture des
lignes historiques (liées 'unknown'). Les sessions offline démo sont étiquetées
et exclues par défaut des stats opérationnelles. Aucune base de production
n'est touchée : chaque test travaille sur une DB temporaire.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from aidesk.config import Matrix, Settings     # noqa: E402
from aidesk.runtime import Desk               # noqa: E402
from aidesk.store import Store                # noqa: E402
from aidesk.types import Features, Trade      # noqa: E402


LEGACY_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts_open REAL, ts_close REAL, symbol TEXT, entry REAL, exit REAL, qty REAL,
  pnl REAL, reason TEXT, agent TEXT, approver TEXT, score REAL, features TEXT
);
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL, symbol TEXT, agent TEXT, agg REAL, verdict INTEGER,
  thesis TEXT, objection TEXT, scores TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, payload TEXT
);
CREATE TABLE IF NOT EXISTS matrix_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, revision INTEGER, note TEXT
);
"""


def make_trade(symbol="X/USDT", pnl=0.12, ts_open=None, ts_close=None) -> Trade:
    f = Features(symbol, 100.0, None, None, 6e6, 0.004, 0.02, 2.0, 0.5, True,
                 time.time())
    return Trade(symbol=symbol, entry=100.0, exit=100.5, qty=1.0, pnl=pnl,
                 reason="TP", ts_open=ts_open or time.time() - 60,
                 ts_close=ts_close or time.time(), agent="TEST", approver=None,
                 score=0.7, features=f)


# 1/2/3 — écriture étiquetée + lecture + historique conservé ----------------------

def test_trade_etaque_live_puis_offline(tmp_path):
    st = Store(str(tmp_path / "t.db"), str(tmp_path / "t.jsonl"))
    st.mode = "live"
    st.add_trade(make_trade("A/USDT"))
    st.mode = "offline"
    st.add_trade(make_trade("B/USDT"))
    modes = {r["symbol"]: r["mode"] for r in st.all_trades()}
    assert modes == {"A/USDT": "live", "B/USDT": "offline"}
    st.close()


def test_migration_sur_base_historique_aucune_perte(tmp_path):
    p = tmp_path / "legacy.db"
    c = sqlite3.connect(str(p))
    c.executescript(LEGACY_SCHEMA)                       # schéma ANCIEN (sans mode)
    c.execute("INSERT INTO trades (ts_open,ts_close,symbol,entry,exit,qty,pnl,"
              "reason,agent,approver,score,features) VALUES "
              "(1.0, 2.0, 'OLD1/USDT', 9, 9.1, 1.0, 0.10, 'TP', 'H', NULL, 0.5, '{}')")
    c.execute("INSERT INTO trades (ts_open,ts_close,symbol,entry,exit,qty,pnl,"
              "reason,agent,approver,score,features) VALUES "
              "(3.0, 4.0, 'OLD2/USDT', 9, 8.9, 1.0, -0.10, 'SL', 'H', NULL, 0.5, '{}')")
    c.commit()
    n_hist = c.execute("SELECT count(*) FROM trades").fetchone()[0]
    c.close()

    st = Store(str(p), str(tmp_path / "legacy.jsonl"))   # ouverture = migration
    rows = st.all_trades()
    assert len(rows) == n_hist == 2                      # anciennes données conservées
    assert {r["symbol"] for r in rows} == {"OLD1/USDT", "OLD2/USDT"}
    assert all(r["mode"] == "unknown" for r in rows)     # provenance historique = inconnue
    pnl_hist = sum(r["pnl"] for r in rows)
    assert abs(pnl_hist - 0.0) < 1e-9                    # PnL intact
    st.mode = "live"
    st.add_trade(make_trade("NEW/USDT"))                 # cohabitation ancien+nouveau
    rows2 = st.all_trades()
    assert len(rows2) == 3
    assert rows2[-1]["mode"] == "live"
    st.close()


# 4 — restauration après redémarrage avec la nouvelle colonne ---------------------

def test_restore_apres_migration_ne_casse_pas(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d1 = Desk(Settings(), Matrix(), offline=True, db_path="t.db", jsonl="t.jsonl")
    d1.broker.buy(Features("T/USDT", 100.0, None, None, 6e6, 0.01, 0.02, 2.0, 0.5,
                           True, time.time()), 5.0, "EXEC", "M1")
    trade = d1.broker.settle(
        Features("T/USDT", 101.5, None, None, 6e6, 0.01, 0.02, 2.0, 0.5, True,
                 time.time()), list(d1.broker.open.values())[0], 101.5, "TP")
    d1.store.add_trade(trade)
    assert trade.pnl > 0
    d1.store.close()

    d2 = Desk(Settings(), Matrix(), offline=True, db_path="t.db", jsonl="t.jsonl")
    restored = [t for t in d2.ledger.trades if t.symbol == "T/USDT"]
    assert len(restored) == 1                            # trade restauré depuis SQLite
    n = d2.store.closed_trades()
    assert n == 1                                        # aucune duplication


# 5 — stats séparées : offline exclu du périmètre opérationnel ---------------------

def seed_modes_db(path: Path) -> None:
    st = Store(str(path), str(path.with_suffix(".jsonl")))
    st.mode = "live"
    st.add_trade(make_trade("LIVE1/USDT", pnl=+1.0))
    st.mode = "offline"
    st.add_trade(make_trade("DEMO/USDT", pnl=+9.99))     # gain de démo bien visible
    st.close()


def run_report(db: Path, *extra: str) -> str:
    cmd = [sys.executable, str(PROJECT / "tools" / "report_week.py"),
           "--db", str(db), *extra]
    out = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT))
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_stats_operationnelles_excluent_offline_par_defaut(tmp_path):
    db = tmp_path / "s.db"
    seed_modes_db(db)
    op = run_report(db)                                  # périmètre opérationnel
    assert "trades clôturés : **1**" in op               # la démo n'est pas comptée
    assert "+1.00 $" in op                               # PnL opérationnel seul
    assert "9.99" not in op                              # le gain de DÉMO est invisible
    assert "live 1" in op and "offline 1" in op          # provenance affichée quand même
    allr = run_report(db, "--mode", "all")
    assert "trades clôturés : **2**" in allr
    assert "+10.99 $" in allr                            # tout, mais étiqueté
    demo = run_report(db, "--mode", "offline")
    assert "trades clôturés : **1**" in demo
    assert "+9.99 $" in demo                             # uniquement la session démo


def test_old_schema_report_ne_crash_pas(tmp_path):
    db = tmp_path / "legacy.db"
    c = sqlite3.connect(str(db))
    c.executescript(LEGACY_SCHEMA)
    c.execute("INSERT INTO trades (ts_open,ts_close,symbol,entry,exit,qty,pnl,"
              "reason,agent,approver,score,features) VALUES "
              "(1.0, %f, 'OLD1/USDT', 9, 9.1, 1.0, 0.10, 'TP', 'H', NULL, 0.5, '{}')"
              % time.time())
    c.commit()
    c.close()
    out = run_report(db)                                 # ancien schéma : pas de colonne mode
    assert "ancien schéma" in out                        # annoncé explicitement
    assert "trades clôturés : **1**" in out              # l'historique reste comptabilisé
    assert "+0.10 $" in out


# 6 — aucun mélange silencieux : le mode vient du feed réel (desk) -----------------

def test_mode_tracke_l_etat_reel_du_feed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = Desk(Settings(), Matrix(), offline=True, db_path="t.db", jsonl="t.jsonl")
    assert d.store.mode == "offline"                     # --offline explicite → démo
    monkeypatch.setattr(d.radar, "scan", lambda *a, **k: [])   # zéro décision → zéro LLM
    f = Features("TT/USDT", 99.0, None, None, 5e6, 0.002, 0.01, 1.4, 0.3, True,
                 time.time())
    st_mode_avant = d.store.mode
    d.store.add_trade(make_trade("TT/USDT"))
    assert st_mode_avant == "offline"
    d.feed.offline = False                               # bascule de source réelle
    d.tick(True)                                         # le tick re-étiquette la session
    assert d.store.mode == "live"
    d.store.add_trade(make_trade("TT2/USDT", pnl=-0.05))
    rows = {r["symbol"]: r["mode"] for r in d.store.all_trades()}
    assert rows["TT/USDT"] == "offline" and rows["TT2/USDT"] == "live"


def test_jsonl_trade_porte_le_mode(tmp_path):
    st = Store(str(tmp_path / "t.db"), str(tmp_path / "t.jsonl"))
    st.mode = "offline"
    st.add_trade(make_trade("J/USDT"))
    ln = json.loads(Path(str(tmp_path / "t.jsonl")).read_text().splitlines()[0])
    assert ln["payload"]["mode"] == "offline"
    st.close()
