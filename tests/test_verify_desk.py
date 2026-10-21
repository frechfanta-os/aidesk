"""Tests E-2 — outils de réconciliation verify_desk (bases synthétiques, jamais
la production). Codes 0/1/2 ; aucun état réel touché (chdir tmp_path).
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from tools.verify_desk import verify   # noqa: E402


def seed_consistent(tmp_path: Path, n_trades: int = 3, with_positions: bool = False) -> None:
    conn = sqlite3.connect(str(tmp_path / "aidesk.db"))
    conn.executescript("""
      CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_open REAL, ts_close REAL, symbol TEXT, entry REAL, exit REAL, qty REAL,
        pnl REAL, reason TEXT, agent TEXT, approver TEXT, score REAL, features TEXT,
        mode TEXT DEFAULT 'unknown');
    """)
    now = time.time()
    for i in range(n_trades):
        conn.execute("INSERT INTO trades (ts_open,ts_close,symbol,entry,exit,qty,"
                     "pnl,reason,agent,approver,score,features,mode) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (now - 100 + i, now - 90 + i, f"T{i}/USDT", 100, 100.2, 1.0,
                      0.15, "TP", "TEST", None, 0.6, "{}", "live"))
    conn.commit()
    conn.close()
    state = {
        "ledger": {"wallet_usdt": 30.0, "vault_usdt": 0.0, "mtm_usdt": 0.0,
                   "equity": 30.0, "wins": n_trades, "losses": 0,
                   "fees_paid": 0.9, "start_usdt": 30.0},
        "positions": [] if not with_positions else
        [{"symbol": "P/USDT", "entry": 1.0, "qty": 2.0, "usdt": 3.0}],
        "trades_closed": [{"symbol": f"T{i}/USDT", "pnl": 0.15}
                          for i in range(n_trades)],
        "risk": {"frozen_treasury": False, "day_frozen": False,
                 "blocks": 0, "day_pnl": 0.0},
        "matrix": {"pass_threshold": 0.62, "revisions": 2},
        "feed": {"offline": False, "name": "binance", "ts": now, "age_s": 1},
        "ticks": 5, "paused": False, "ts": now,
    }
    (tmp_path / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (tmp_path / "events.jsonl").write_text(
        json.dumps({"ts": now, "kind": "trade", "payload": {}}) + "\n",
        encoding="utf-8")


def test_tout_coherent_code_0(tmp_path):
    seed_consistent(tmp_path)
    code, msgs = verify(tmp_path)
    assert code == 0
    joined = "\n".join(msgs)
    assert "SQLite == state.json == 3" in joined
    assert "trades clôturés : SQLite == state.json == 3" in joined


def test_drift_trades_code_1(tmp_path):
    seed_consistent(tmp_path, n_trades=2)
    st = json.loads((tmp_path / "state.json").read_text())
    st["trades_closed"].append({"symbol": "FANTOME/USDT"})   # +1 vs SQLite
    (tmp_path / "state.json").write_text(json.dumps(st))
    code, msgs = verify(tmp_path)
    assert code == 1
    assert any("trades SQLite=2 vs state.json=3" in m for m in msgs)


def test_montant_negatif_et_equity_cassees_code_1(tmp_path):
    seed_consistent(tmp_path)
    st = json.loads((tmp_path / "state.json").read_text())
    st["ledger"]["wallet_usdt"] = -1.0                        # impossible sainement
    st["trades_closed"] = st["trades_closed"][:1]             # drift aussi
    (tmp_path / "state.json").write_text(json.dumps(st))
    code, msgs = verify(tmp_path)
    assert code == 1
    assert any("négatif" in m for m in msgs)


def test_missing_files_code_2(tmp_path):
    code, msgs = verify(tmp_path)
    assert code == 2 and any("absent" in m for m in msgs)


def test_state_casse_code_2(tmp_path):
    seed_consistent(tmp_path)
    (tmp_path / "state.json").write_text("{pas du json", encoding="utf-8")
    code, _ = verify(tmp_path)
    assert code == 2


def test_position_corrompue_detectee(tmp_path):
    seed_consistent(tmp_path, with_positions=True)
    st = json.loads((tmp_path / "state.json").read_text())
    st["positions"][0]["qty"] = 0                             # qty nulle impossible
    (tmp_path / "state.json").write_text(json.dumps(st))
    code, msgs = verify(tmp_path)
    assert code == 1 and any("position corrompue" in m for m in msgs)


def test_events_queue_corrompue_code_1(tmp_path):
    seed_consistent(tmp_path)
    (tmp_path / "events.jsonl").write_text(
        json.dumps({"ts": 1, "kind": "boot"}) + "\n{\"truncat",
        encoding="utf-8")
    code, msgs = verify(tmp_path)
    assert code == 1 and any("queue non parsable" in m for m in msgs)


def test_provenance_repartie(tmp_path):
    seed_consistent(tmp_path, n_trades=2)
    conn = sqlite3.connect(str(tmp_path / "aidesk.db"))
    conn.execute("INSERT INTO trades (ts_open,ts_close,symbol,entry,exit,qty,pnl,"
                 "reason,agent,approver,score,features,mode) VALUES "
                 "(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (time.time() - 5, time.time(), "DEMO/USDT", 1, 1, 1, 0.0, "TP",
                  "TEST", None, 0.5, "{}", "offline"))
    conn.commit()
    conn.close()
    st = json.loads((tmp_path / "state.json").read_text())   # état EGENC
    st["trades_closed"].append({"symbol": "DEMO/USDT", "pnl": 0.0})
    (tmp_path / "state.json").write_text(json.dumps(st), encoding="utf-8")
    code, msgs = verify(tmp_path)
    assert code == 0
    assert any("offline 1" in m and "live 2" in m for m in msgs)
