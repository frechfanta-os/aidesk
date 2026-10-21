from __future__ import annotations

"""Export du corpus de trades comme DATASET VERSIONNÉ (Phase F).

Produit, par défaut dans docs/data/exp/ :
  trades_YYYYMMDDTHHMM.csv               lignes triées par id (ordre déterministe)
  trades_YYYYMMDDTHHMM.manifest.json     sha256 du CSV, comptes, provenance

Le manifeste porte l'avertissement explicite : données PAPER expérimentales,
échantillon insuffisant → aucune garantie de performance future. La base est
ouverte en URI ro : cet outil n'écrit JAMAIS dans la DB. Le CSV du manifeste
est censé être commité (git) pour garder une série historique immuable.
"""

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

DISCLAIMER = ("DONNÉES PAPER EXPÉRIMENTALES — échantillon insuffisant, "
              "aucune garantie de performance future ; ne constitue pas une "
              "information financière.")

COLUMNS = ["id", "ts_open", "ts_close", "symbol", "entry", "exit", "qty",
           "pnl", "reason", "agent", "approver", "score", "mode"]


def _load_rows(db_path: Path) -> tuple[list[dict], int]:
    """Lecture 100 % read-only (URI) ; DB ancienne sans colonne mode → unknown."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        has_mode = "mode" in {r[1] for r in conn.execute("PRAGMA table_info(trades)")}
        sel = COLUMNS if has_mode else [c for c in COLUMNS if c != "mode"]
        rows = [dict(zip(sel, r)) for r in
                conn.execute(f"SELECT {','.join(sel)} FROM trades ORDER BY id")]
        return rows, 1 if has_mode else 0
    finally:
        conn.close()


def export(root: str | Path = ".", out_dir: str | Path | None = None
           ) -> tuple[Path, Path]:
    """Écrit le CSV + manifeste ; retourne les deux chemins. Rejouable :
    le même contenu de base → même CSV (manifeste sha identique au contenu)."""
    r = Path(root)
    db = r / "aidesk.db"
    if not db.exists():
        raise SystemExit(f"aidesk.db introuvable sous {r}")
    rows, has_mode = _load_rows(db)
    stamp = time.strftime("%Y%m%dT%H%M", time.gmtime())
    out = Path(out_dir) if out_dir else r / "docs" / "data" / "exp"
    out.mkdir(parents=True, exist_ok=True)
    csv_p = out / f"trades_{stamp}.csv"

    data = [[r2[c] if c in r2 else "unknown" for c in COLUMNS] for r2 in rows]
    with open(csv_p, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        w.writerows(data)

    blob = csv_p.read_bytes()
    by_mode: dict[str, int] = {}
    for r2 in rows:
        m = r2.get("mode", "unknown")
        by_mode[m] = by_mode.get(m, 0) + 1
    wins = sum(1 for r2 in rows if r2["pnl"] > 0)
    losses = sum(1 for r2 in rows if r2["pnl"] < 0)
    manifest = {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "csv_sha256": hashlib.sha256(blob).hexdigest(),
        "rows": len(rows),
        "by_mode": by_mode,
        "wins": wins, "losses": losses,
        "net_pnl": round(sum(float(r2["pnl"]) for r2 in rows), 4),
        "mode_column_in_db": bool(has_mode),
        "warning": DISCLAIMER,
    }
    man_p = out / f"trades_{stamp}.manifest.json"
    man_p.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                     encoding="utf-8")
    return csv_p, man_p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default=None, help="dossier de sortie (défaut docs/data/exp)")
    a = ap.parse_args(argv)
    csv_p, man_p = export(a.root, a.out)
    man = json.loads(man_p.read_text())
    print(f"  CSV     : {csv_p} ({man['rows']} lignes, {man['csv_sha256'][:12]}…)")
    print(f"  manifeste : {man_p}")
    print(f"  W/L : {man['wins']}/{man['losses']} | net {man['net_pnl']:+.2f}$ | "
          f"{man['by_mode']}")
    print(f"  ⚠ {man['warning']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
