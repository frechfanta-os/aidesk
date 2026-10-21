from __future__ import annotations

"""Réconciliation du desk : SQLite ↔ state.json ↔ events.jsonl.

Usage :
    python3 tools/verify_desk.py            # cwd = racine du desk
Codes : 0 = cohérent · 1 = avertissements (détail imprimé) · 2 = fatal
(fichiers manquants/illisibles). Lecture seule — la base est ouverte en
URI ro ; le JSONL n'est lu que lignes complètes déjà écrites.
"""

import json
import sqlite3
import sys
from pathlib import Path


def verify(root: str | Path = ".") -> tuple[int, list[str]]:
    """Retour (code, messages). Jamais d'écriture, jamais de lock longue durée."""
    r = Path(root)
    out: list[str] = []
    code = 0

    state_p = r / "state.json"
    db_p = r / "aidesk.db"
    ev_p = r / "events.jsonl"
    for p in (state_p, db_p, ev_p):
        if not p.exists():
            return 2, [f"FATAL : {p.name} absent — desk jamais initialisé ?"]

    try:
        state = json.loads(state_p.read_text(encoding="utf-8"))
    except Exception as e:
        return 2, [f"FATAL : state.json illisible ({type(e).__name__}: {e})"]
    try:
        conn = sqlite3.connect(f"file:{db_p}?mode=ro", uri=True)
    except Exception as e:
        return 2, [f"FATAL : SQLite indisponible en lecture ({e})"]

    led = state.get("ledger") or {}
    if not led:
        conn.close()
        return 2, ["FATAL : state.json sans ledger (restore jamais effectué ?)"]

    # 1 — correspondance des trades clôturés (SQLite = source de vérité)
    try:
        row = conn.execute(
            "SELECT count(*), COALESCE(sum(pnl > 0), 0), COALESCE(sum(pnl < 0), 0), "
            "round(COALESCE(sum(pnl), 0.0), 2) FROM trades").fetchone()
        n_db, wins, losses, net_pnl = row
        n_mode = dict(conn.execute(
            "SELECT COALESCE(mode,'unknown'), count(*) FROM trades GROUP BY 1"))
    except Exception as e:
        conn.close()
        return 2, [f"FATAL : requête trades a échoué ({e})"]
    closed_state = state.get("trades_closed") or []
    if n_db != len(closed_state):
        code = max(code, 1)
        out.append(f"AVERT. trades SQLite={n_db} vs state.json={len(closed_state)} "
                   f"— un snapshot fraîchement écrit n'a pas encore la fin de tick, "
                   "sinon drift de restauration à investiguer")
    else:
        out.append(f"OK trades clôturés : SQLite == state.json == {n_db} "
                   f"({wins}W/{losses}L, net {net_pnl:+.2f} $)")

    # 2 — comptabilité de base : montants non négatifs, équité cohérente
    wallet, vault, mtm = (float(led.get("wallet_usdt", 0.0)),
                          float(led.get("vault_usdt", 0.0)),
                          float(led.get("mtm_usdt", 0.0)))
    if wallet < 0 or vault < 0:
        code = max(code, 1)
        out.append(f"AVERT. montant négatif : wallet={wallet} vault={vault}")
    else:
        out.append(f"OK trésorerie : wallet {wallet:.2f} $, vault {vault:.2f} $")
    eq_raw = led.get("equity", 0.0)
    # equity peut être une COURBE (liste de points, du snapshot) ou un scalaire
    eq = float(eq_raw[-1]) if isinstance(eq_raw, list) and eq_raw else \
        float(eq_raw if not isinstance(eq_raw, list) else 0.0)
    if eq and abs(eq - (wallet + vault + mtm)) > 0.01:
        code = max(code, 1)
        out.append(f"AVERT. equity {eq:.2f} ≠ wallet+vault+mtm "
                   f"{wallet + vault + mtm:.2f}")
    else:
        out.append(f"OK equity ≈ {eq:.2f} $")

    # 3 — positions ouvertes : positité stricte des champs de position
    for p in state.get("positions") or []:
        if not p.get("entry") or p.get("qty", 0) <= 0 or p.get("usdt", 0) <= 0:
            code = max(code, 1)
            out.append(f"AVERT. position corrompue : {p.get('symbol')} "
                       f"entry={p.get('entry')} qty={p.get('qty')} usdt={p.get('usdt')}")
    if not (state.get("positions") or []):
        out.append("OK positions ouvertes : aucune")

    # 4 — provenance (B5) : répartition et valeur du corpus
    parts = ", ".join(f"{m} {n}" for m, n in sorted(n_mode.items())) or "vide"
    out.append(f"OK provenance modes : {parts}")
    if n_mode.get("offline", 0) and not n_mode.get("live") and not n_mode.get("unknown"):
        out.append("INFO : corpus 100 % offline (démo) — opérationalité nulle, normal")

    # 5 — événements : dernière ligne parseable (JSONL non corrompu en queue)
    try:
        last = ev_p.read_text(encoding="utf-8").splitlines()[-1]
        data = json.loads(last)
        kind = data.get("kind", "?")
        out.append(f"OK events.jsonl dernière ligne : kind={kind}")
    except (IndexError, ValueError) as e:
        code = max(code, 1)
        out.append(f"AVERT. events.jsonl queue non parsable ({e}) — corrompu en écriture ?")

    # 6 — matrice/gels : champs attendus
    risks = state.get("risk") or {}
    for k in ("frozen_treasury", "day_frozen", "blocks", "day_pnl"):
        if k not in risks:
            code = max(code, 1)
            out.append(f"AVERT. champs risk.{k} absent de state.json")
    out.append(f"OK risk : gel_tresorerie={risks.get('frozen_treasury')} "
               f"gel_jour={risks.get('day_frozen')} blocs={risks.get('blocks')}")
    conn.close()
    return code, out


def main(argv: list[str] | None = None) -> int:
    root = Path(argv[1]) if argv and len(argv) > 1 else Path(".")
    code, lines = verify(root)
    print("\n".join("  " + ln for ln in lines))
    print(("OK — cohérence vérifiée" if code == 0
           else "AVERTISSEMENTS" if code == 1 else "FATAL") + f" · code {code}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
