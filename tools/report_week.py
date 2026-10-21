from __future__ import annotations

"""Rapport hebdo depuis SQLite : equity, winrate, espérance, drawdown, matrice.

Usage :
    python3 tools/report_week.py                 # 7 derniers jours, sortie console
    python3 tools/report_week.py --days 30 -o docs/REPORTS/auto.md
"""

import argparse
import sqlite3
import time
from pathlib import Path


def spark(series: list[float], width: int = 40) -> str:
    if len(series) < 2:
        return "(trop peu de points)"
    lo, hi = min(series), max(series)
    span = (hi - lo) or 1.0
    blocks = "▁▂▃▄▅▆▇█"
    out = []
    for i in range(width):
        idx = round(i * (len(series) - 1) / (width - 1))
        out.append(blocks[min(7, int((series[idx] - lo) / span * 7.999))])
    return "".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="aidesk.db")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--start", type=float, default=None,
                    help="banque de départ (défaut : lu du event boot)")
    ap.add_argument("-o", "--output", default=None, help="fichier markdown potentiel")
    args = ap.parse_args()

    c = sqlite3.connect(args.db)
    since = time.time() - args.days * 86400
    if args.start is not None:
        start = args.start
    else:
        import json
        row = c.execute("SELECT payload FROM events WHERE kind='boot' "
                        "ORDER BY id ASC LIMIT 1").fetchone()
        start = 30.0
        if row:
            try:
                start = float(json.loads(row[0]).get("start_usdt", 30.0))
            except Exception:
                pass

    rows = c.execute(
        "SELECT symbol,entry,exit,qty,pnl,reason,ts_close,agent,approver,score "
        "FROM trades WHERE ts_close >= ? ORDER BY ts_close", (since,)).fetchall()
    n = len(rows)
    pnl = sum(r[4] for r in rows)
    wins = sum(1 for r in rows if r[4] > 0)
    exp = (pnl / n) if n else 0.0
    equity = [start]
    for r in rows:
        equity.append(round(equity[-1] + r[4], 4))
    peak, maxdd = start, 0.0
    for v in equity:
        peak = max(peak, v)
        maxdd = max(maxdd, (peak - v) / peak * 100)

    reasons: dict[str, int] = {}
    for r in rows:
        reasons[r[5]] = reasons.get(r[5], 0) + 1
    dec = c.execute("SELECT count(*), sum(verdict) FROM decisions WHERE ts >= ?",
                    (since,)).fetchone()
    revs = c.execute("SELECT count(*) FROM matrix_history").fetchone()[0]
    agents_top = c.execute(
        "SELECT agent, count(*), sum(pnl) FROM trades WHERE ts_close >= ? "
        "GROUP BY agent ORDER BY sum(pnl) DESC LIMIT 5", (since,)).fetchall()

    lines = [
        f"# RAPPORT DESK — {args.days} derniers jours",
        f"généré {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}",
        "",
        f"- trades clôturés : **{n}** (W {wins} / L {n - wins}) → winrate "
        f"{100 * wins / n:.0f} %" if n else "- trades clôturés : **0** (trop tôt)",
        f"- PnL cumulé : **{pnl:+.2f} $** | espérance/ trade : **{exp:+.4f} $**",
        f"- frais intégrés au PnL ; drawdown max : **{maxdd:.2f} %** peak {max(equity):.2f} $",
        f"- decisions : {dec[0]} évaluées, {dec[1] or 0} acceptées | matrice révisions : {revs}",
        f"- courbe équité : `{spark(equity)}`",
        "",
        "## Raisons de sortie",
        *(f"- {k}: {v}" for k, v in sorted(reasons.items(), key=lambda x: -x[1])),
        "",
        "## Top agents (par PnL)",
        *(f"- {a} : {cnt} trade(s), {tot:+.2f} $" for a, cnt, tot in agents_top),
        "",
        "— rapport automatique, chiffres bruts de SQLite. Pas de maquillage, jamais.",
    ]
    md = "\n".join(lines)
    print(md)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md + "\n", encoding="utf-8")
        print(f"\n→ écrit : {out}")


if __name__ == "__main__":
    main()
