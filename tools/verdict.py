from __future__ import annotations

"""Porte de verdict statistique (Phase F) — lecture seule du corpus.

Définitions MAÎTRISÉES (loi forte du projet) :
  • OPÉRATIONNEL  = trades `live` ou `unknown` (bien pré-B5, réellement live).
  • EXCLUS        = `offline` (dé random walk, jamais comptés).
  • La porte est ≥ 30 trades OPÉRATIONNELS — les démo ne serviront jamais à
    arrondir l'échantillon.
  • < 30 → code 1 et section NON-QUALIFIÉ (descriptif seul). Aucun écart de
    neutralité statistique : intervalles de confiance (Wilson), jamais les
    mots rentable/profitable/garanti.
  • Split chronologique 60/40 : calibration (la plus ancienne) vs validation
    (la plus récente). Le hors-échantillon est DÉCOUPLÉ dans le temps — il ne
    prédit rien.

Codes : 0 = porte atteinte · 1 = porte non atteinte · 2 = fatal (DB).
"""

import json
import math
import sqlite3
import statistics
import sys
from pathlib import Path

OP_MODES = ("live", "unknown")
PORTE = 30
SPLIT = 0.6          # calibration = les 60 % les plus anciens
Z = 1.959963985      # quantile 95 % (normal)


def wilson(k: int, n: int) -> tuple[float, float]:
    """Intervalle de Wilson 95 % d'une proportion k/n (n nul → (0, 1))."""
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + Z * Z / n
    center = (p + Z * Z / (2 * n)) / denom
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / denom
    return (center - half, center + half)


def max_drawdown(start: float, pnls: list[float]) -> float:
    """Retrait maximal réalisé (pic → creux) sur la courbe d'équité réalisée."""
    eq = start
    peak = start
    dd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return dd


def _start_usdt(root: Path) -> float | None:
    """Banque de départ selon state.json ; None si absent."""
    try:
        sp = root / "state.json"
        if not sp.exists():
            return None
        led = (json.loads(sp.read_text(encoding="utf-8")).get("ledger") or {})
        v = led.get("start_usdt")
        return float(v) if v is not None else None
    except Exception:
        return None


def verdict(root: str | Path = ".") -> tuple[int, list[str]]:
    r = Path(root)
    db = r / "aidesk.db"
    if not db.exists():
        return 2, [f"FATAL : {db} absent"]
    conn = None
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = [dict(zip(("ts_open", "pnl", "mode"), t)) for t in conn.execute(
            "SELECT COALESCE(ts_open,0), pnl, COALESCE(mode,'unknown') "
            "FROM trades ORDER BY ts_open, id")]
    except Exception as e:
        return 2, [f"FATAL : lecture trades impossible ({e})"]
    finally:
        if conn is not None:
            conn.close()

    op = [row for row in rows if row["mode"] in OP_MODES]
    off = len(rows) - len(op)
    out: list[str] = []
    out.append(f"corpus : {len(op)} opérationnel(s) | {off} offline EXCLUS (démo)")
    out.append("AUCUNE garantie : données PAPER expérimentales ; "
               "le hors-échantillon ne prédit rien.")

    n = len(op)
    if n < PORTE:
        out.append(f"NON-QUALIFIÉ — porte non atteinte ({n}/{PORTE}). "
                   "Aucun verdict ne s'applique.")
    else:
        out.append(f"PORTE ATTEINTE ({n}/{PORTE}) — descriptif exact, "
                   "strictement ex-post :")

    pnls = [float(row["pnl"]) for row in op]
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)
    decided = wins + losses
    net = round(sum(pnls), 4)
    out.append(f"  W/L {wins}/{losses}" +
               (f" | {n - decided} ni l'un ni l'autre (pnl=0)" if decided < n else "") +
               f" | net {net:+.4f} $")
    if decided:
        lo, hi = wilson(wins, decided)
        out.append(f"  taux de victoire (décidés) {wins}/{decided} = "
                   f"{wins / decided:.3f}  IC95 % Wilson [{lo:.3f} ; {hi:.3f}]")
    if n >= 2:
        mean = statistics.mean(pnls)
        try:
            se = statistics.stdev(pnls) / math.sqrt(n)
        except statistics.StatisticsError:
            se = 0.0
        out.append(f"  PnL/trade moyen {mean:+.4f} $  ± 1.96·SE "
                   f"[{mean - 1.96 * se:+.4f} ; {mean + 1.96 * se:+.4f}] "
                   f"(approx normale, SE={se:.4f})")
    if wins and losses:
        pf = sum(p for p in pnls if p > 0) / abs(sum(p for p in pnls if p < 0))
        out.append(f"  profit factor {pf:.3f}  (ex-post, descriptif)")
    dd = max_drawdown(_start_usdt(r) or 30.0, pnls)
    out.append(f"  retrait max réalisé {dd:.4f} $ (courbe d'équité, ex-post)")

    if n >= PORTE:
        k = int(n * SPLIT)
        cal, val = pnls[:k], pnls[k:]
        for label, part in (("calibration (les 60 % les plus anciens)", cal),
                            ("validation (les suivantes)", val)):
            sub_w = sum(1 for p in part if p > 0)
            sub_l = sum(1 for p in part if p < 0)
            lo, hi = wilson(sub_w, sub_w + sub_l)
            out.append(f"  {label} : n={len(part)} W/L {sub_w}/{sub_l} net "
                       f"{sum(part):+.4f} $ IC95 % [{lo:.3f} ; {hi:.3f}]")
        out.append("  Le HORS-ÉCHANTILLON est temps-découplé : comparer calibration")
        out.append("  et validation décrit, ne PREDIT pas. Jamais de rentabilité affichée.")
    return (0 if n >= PORTE else 1), out


def main(argv: list[str] | None = None) -> int:
    root = Path(argv[1]) if argv and len(argv) > 1 else Path(".")
    code, lines = verdict(root)
    print("\n".join("  " + ln for ln in lines))
    print(f"code {code} " + ("(porte atteinte)" if code == 0 else
                             "(non qualifié)" if code == 1 else "(fatal)"))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
