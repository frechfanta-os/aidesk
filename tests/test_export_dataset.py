"""Tests F-1 — export de dataset versionné (bases synthétiques tmp, read-only).

Le CSV doit être déterministe, le manifeste doit porter le sha256 du fichier
réel et l'avertissement « rien n'est garanti ». La DB n'est JAMAIS modifiée.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from tools.export_dataset import export  # noqa: E402


def seed(tmp_path: Path, with_mode: bool = True) -> Path:
    col = ", mode TEXT DEFAULT 'unknown'" if with_mode else ""
    conn = sqlite3.connect(str(tmp_path / "aidesk.db"))
    conn.executescript(f"""
      CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_open REAL, ts_close REAL, symbol TEXT, entry REAL, exit REAL, qty REAL,
        pnl REAL, reason TEXT, agent TEXT, approver TEXT, score REAL,
        features TEXT{col});
    """)
    for i, mode in enumerate(("unknown", "live", "live", "offline")):
        vals = "(1.0, 2.0, ?, 100.0, 100.2, 1.0, ?, 'TP', 'TEST', NULL, 0.6, '()')"
        if with_mode:
            conn.execute("INSERT INTO trades (ts_open,ts_close,symbol,entry,exit,"
                         "qty,pnl,reason,agent,approver,score,features,mode) "
                         f"VALUES {vals[:-1]}, ?)",
                         (f"T{i}/USDT", (0.2 if i % 2 == 0 else -0.1), mode))
        else:
            conn.execute("INSERT INTO trades (ts_open,ts_close,symbol,entry,exit,"
                         "qty,pnl,reason,agent,approver,score,features) "
                         f"VALUES {vals}", (f"T{i}/USDT",
                                            (0.2 if i % 2 == 0 else -0.1)))
    conn.commit()
    conn.close()
    return tmp_path


def test_export_deterministe_et_manifeste_sha(tmp_path):
    r = seed(tmp_path)
    csv_p, man_p = export(r, out_dir=tmp_path / "exp")
    blob = csv_p.read_bytes()
    assert hashlib.sha256(blob).hexdigest() == \
        json.loads(man_p.read_text())["csv_sha256"]
    # re-exécution au même flux → CSV identique bit à bit
    csv2, man2 = export(r, out_dir=tmp_path / "exp2")
    assert csv2.read_bytes() == blob


def test_contenu_csv_tri_et_colonnes(tmp_path):
    r = seed(tmp_path)
    csv_p, _ = export(r, out_dir=tmp_path / "exp")
    lines = csv_p.read_text().splitlines()
    assert lines[0] == ("id,ts_open,ts_close,symbol,entry,exit,qty,pnl,reason,"
                        "agent,approver,score,mode")
    assert lines[1].split(",")[3] == "T0/USDT"
    assert "unknown" in lines[1]                      # mode 'unknown' porté


def test_manifeste_modes_et_disclaimer(tmp_path):
    r = seed(tmp_path)
    _, man_p = export(r, out_dir=tmp_path / "exp")
    man = json.loads(man_p.read_text())
    assert man["by_mode"] == {"unknown": 1, "live": 2, "offline": 1}
    assert man["rows"] == 4 and man["wins"] == 2 and man["losses"] == 2
    assert "aucune garantie" in man["warning"]
    assert man["mode_column_in_db"] is True


def test_db_ancienne_sans_colonne_mode(tmp_path):
    r = seed(tmp_path, with_mode=False)
    csv_p, man_p = export(r, out_dir=tmp_path / "exp")
    man = json.loads(man_p.read_text())
    assert man["rows"] == 4 and man["by_mode"] == {"unknown": 4}
    assert man["mode_column_in_db"] is False
    assert "unknown" in csv_p.read_text().splitlines()[1]  # colonne substituée


def test_export_ne_modifie_jamais_la_db(tmp_path):
    r = seed(tmp_path)
    db = r / "aidesk.db"
    before = db.read_bytes()
    export(r, out_dir=tmp_path / "exp")
    assert db.read_bytes() == before                    # lecture seule stricte
