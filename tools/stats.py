from __future__ import annotations

import json
import sqlite3
import sys


def main(path: str = "aidesk.db") -> None:
    c = sqlite3.connect(path)
    n = c.execute("SELECT count(*) FROM trades").fetchone()[0]
    wins = c.execute("SELECT count(*) FROM trades WHERE pnl > 0").fetchone()[0]
    pnl = c.execute("SELECT sum(pnl) FROM trades").fetchone()[0] or 0.0
    print(f"trades clôturés : {n} | W {wins} / L {n - wins} | PnL cumulé {pnl:+.4f} $")
    if n:
        print("\n-- trades --")
        for r in c.execute(
            "SELECT symbol, entry, exit, pnl, reason, agent, approver FROM trades ORDER BY id"
        ).fetchall():
            print(f"  {r[0]:<14} {r[1]:.6g} → {r[2]:.6g} | {r[3]:+.4f} $ | "
                  f"{r[4]:<8} | {r[5]}/{r[6] or '—'}")
    dec = c.execute("SELECT count(*), sum(verdict) FROM decisions").fetchone()
    print(f"\ndecisions : {dec[0]} évaluées, {dec[1] or 0} acceptées")
    rev = c.execute("SELECT count(*) FROM matrix_history").fetchone()[0]
    print(f"matrix_history : {rev} révisions | events : "
          f"{c.execute('SELECT count(*) FROM events').fetchone()[0]}")
    if "--verbose" in sys.argv:
        print("\n-- dernières décisions --")
        for r in c.execute(
            "SELECT ts,symbol,agent,agg,verdict,thesis FROM decisions ORDER BY id DESC LIMIT 10"
        ).fetchall():
            print(f"  {r[1]:<14} score {r[3]:.2f} → {'ACHAT' if r[4] else 'refus'} ({r[2]})")
            print(f"    {r[5][:160]}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "aidesk.db")
