from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any, Iterable

SCHEMA = """
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


class Store:
    def __init__(self, path: str = "aidesk.db", jsonl: str = "events.jsonl") -> None:
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self.jsonl_path = jsonl
        self._fh = open(jsonl, "a", encoding="utf-8")

    def add_trade(self, t) -> None:
        self.conn.execute(
            "INSERT INTO trades (ts_open,ts_close,symbol,entry,exit,qty,pnl,reason,agent,approver,score,features)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (t.ts_open, t.ts_close, t.symbol, t.entry, t.exit, t.qty, t.pnl, t.reason,
             t.agent, t.approver, t.score, json.dumps(t.features.__dict__)),
        )
        self.conn.commit()
        self._emit("trade", t.__dict__ | {"features": t.features.__dict__})

    def add_decision(self, d) -> None:
        self.conn.execute(
            "INSERT INTO decisions (ts,symbol,agent,agg,verdict,thesis,objection,scores)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (d.ts, d.symbol, d.agent, d.agg, int(d.verdict), d.thesis, d.objection,
             json.dumps(d.scores)),
        )
        self.conn.commit()
        self._emit("decision", d.__dict__ | {"scores": d.scores})

    def add_event(self, kind: str, payload: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO events (ts,kind,payload) VALUES (?, ?, ?)",
            (time.time(), kind, json.dumps(payload)),
        )
        self.conn.commit()
        self._emit(kind, payload)

    def add_matrix(self, revision: int, note: str) -> None:
        self.conn.execute(
            "INSERT INTO matrix_history (ts,revision,note) VALUES (?, ?, ?)",
            (time.time(), revision, note),
        )
        self.conn.commit()

    def trades(self) -> Iterable[tuple]:
        return self.conn.execute(
            "SELECT symbol,pnl,reason,ts_open,ts_close FROM trades ORDER BY id"
        ).fetchall()

    def all_trades(self) -> list[dict]:
        cols = ("symbol,entry,exit,qty,pnl,reason,ts_open,ts_close,agent,approver,score")
        rows = self.conn.execute(f"SELECT {cols} FROM trades ORDER BY id").fetchall()
        keys = cols.split(",")
        out = [dict(zip(keys, r)) for r in rows]
        return out

    def closed_trades(self) -> int:
        return self.conn.execute("SELECT count(*) FROM trades").fetchone()[0]

    def wins(self) -> int:
        return self.conn.execute("SELECT count(*) FROM trades WHERE pnl > 0").fetchone()[0]

    def _emit(self, kind: str, payload: dict[str, Any]) -> None:
        self._fh.write(json.dumps({"ts": time.time(), "kind": kind, "payload": payload},
                                  default=str) + "\n")
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.close()
        finally:
            self.conn.close()
