from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
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
CREATE INDEX IF NOT EXISTS idx_trades_ts_close ON trades(ts_close);
CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(ts);
"""


def _archive_name(jsonl: str | Path, stamp: str) -> Path:
    """Nom d'archive unique : events.jsonl.archive-<stamp>[.N] (JAMAIS écraser)."""
    base = Path(f"{jsonl}.archive-{stamp}")
    p, n = base, 1
    while p.exists():
        p = Path(f"{base}.{n}")
        n += 1
    return p


class Store:
    """SQLite (source de vérité) + miroir JSONL borné par ARCHIVE (jamais effacé).

    Le miroir `events.jsonl` est tourné (renommé en `.archive-<utc stamp>`)
    quand il dépasse `jsonl_max_bytes` (défaut 5 Mo). Aucune ligne n'est
    détruite ; l'historique reste intact dans les archives et dans SQLite.
    """
    DEFAULT_JSONL_BYTES = 5_000_000

    def __init__(self, path: str = "aidesk.db", jsonl: str = "events.jsonl",
                 jsonl_max_bytes: int | None = None) -> None:
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        # B5 — provenance de session (migration ADDITIVE, transactionnelle, sans
        # réécriture des anciennes lignes) : les trades historiques lisent 'unknown'.
        # Réversible en lecture : DROP COLUMN trades.mode (SQLite ≥ 3.35) recrée
        # exactement le schéma d'origine sans perte.
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(trades)")}
        if "mode" not in cols:
            self.conn.execute(
                "ALTER TABLE trades ADD COLUMN mode TEXT DEFAULT 'unknown'")
            self.conn.commit()
        self.mode: str = "unknown"      # 'live' | 'offline' | 'unknown' (fixé par le desk)
        self.jsonl_path = jsonl
        # B8 — rotation archivistique du miroir JSONL : seuil en octets.
        self.jsonl_max_bytes = (self.DEFAULT_JSONL_BYTES if jsonl_max_bytes is None
                                else max(1, int(jsonl_max_bytes)))
        self._open_jsonl()

    def _open_jsonl(self) -> None:
        self._fh = open(self.jsonl_path, "a", encoding="utf-8")

    def _rotate_if_needed(self) -> None:
        try:
            size = self._fh.tell()
        except (OSError, ValueError):
            return
        if size < self.jsonl_max_bytes:
            return
        self._fh.close()
        stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
        arch = _archive_name(self.jsonl_path, stamp)   # suffixe .N si collision
        os.rename(self.jsonl_path, arch)               # RENOMME — ne détruit jamais
        self._open_jsonl()
        self._fh.write(json.dumps(
            {"ts": time.time(), "kind": "rotate",
             "payload": {"archive": arch.name, "bytes": size}},
            default=str) + "\n")
        self._fh.flush()

    def add_trade(self, t) -> None:
        self.conn.execute(
            "INSERT INTO trades (ts_open,ts_close,symbol,entry,exit,qty,pnl,reason,"
            "agent,approver,score,features,mode)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (t.ts_open, t.ts_close, t.symbol, t.entry, t.exit, t.qty, t.pnl, t.reason,
             t.agent, t.approver, t.score, json.dumps(t.features.__dict__),
             self.mode if self.mode else "unknown"),
        )
        self.conn.commit()
        self._emit("trade", t.__dict__ | {"features": t.features.__dict__,
                                          "mode": self.mode})

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
        keys = ["symbol", "entry", "exit", "qty", "pnl", "reason", "ts_open",
                "ts_close", "agent", "approver", "score", "mode"]
        rows = self.conn.execute(
            "SELECT symbol,entry,exit,qty,pnl,reason,ts_open,ts_close,agent,"
            "approver,score,COALESCE(mode,'unknown') FROM trades ORDER BY id"
        ).fetchall()
        return [dict(zip(keys, r)) for r in rows]

    def closed_trades(self) -> int:
        return self.conn.execute("SELECT count(*) FROM trades").fetchone()[0]

    def wins(self) -> int:
        return self.conn.execute("SELECT count(*) FROM trades WHERE pnl > 0").fetchone()[0]

    def _emit(self, kind: str, payload: dict[str, Any]) -> None:
        self._rotate_if_needed()   # B8 : rotation archivistique AVANT écriture
        self._fh.write(json.dumps({"ts": time.time(), "kind": kind, "payload": payload},
                                  default=str) + "\n")
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.close()
        finally:
            self.conn.close()
