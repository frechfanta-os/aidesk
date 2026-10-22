from __future__ import annotations

"""Superviseur du desk : relance après crash ET après figeage.

Deux déclencheurs de relance :
  1. crash (rc != 0) — comme avant ;
  2. FIGEAGE : processus vivant mais aucune écriture de tick — `state.json` plus
     vieux que le seuil. Jusqu'ici un hang était invisible (observation du
     2026-10-21 : alarme humaine non reproductible car non outillée).

Le seuil par défaut (900 s) DOIT dépasser le pire blocage légitime d'un tick
(breaker LLM = 600 s), sinon on tuerait un desk sain en attente du breaker.

Usage : python3 tools/watchdog.py
Env   : AIDESK_MAX_RESTARTS · AIDESK_WATCHDOG_COOLDOWN · AIDESK_ARGS
        AIDESK_WATCHDOG_STALE_S (défaut 900) · AIDESK_WATCHDOG_POLL_S (défaut 20)
"""

import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def desk_stale(ts: str | None, now: float, max_age: float) -> bool:
    """True = dernier tick plus vieux que max_age (figeage démontré).

    ts None/illisible → False par précaution (jamais de kill sur doute :
    botte de démarrage, course d'écriture, corruption parseable).
    """
    if not ts or not isinstance(ts, str):
        return False
    try:
        t = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ") \
            .replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return False
    return (now - t) > max_age


def _read_ts(path: Path) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("ts")
    except Exception:
        return None


def main() -> None:
    max_restarts = int(os.getenv("AIDESK_MAX_RESTARTS", "50"))
    cooldown = float(os.getenv("AIDESK_WATCHDOG_COOLDOWN", "10"))
    stale_s = float(os.getenv("AIDESK_WATCHDOG_STALE_S", "900"))
    poll_s = float(os.getenv("AIDESK_WATCHDOG_POLL_S", "20"))
    extra = shlex.split(os.getenv("AIDESK_ARGS", ""))
    state_p = ROOT / "state.json"
    n = 0
    while n < max_restarts:
        print(f"[watchdog {time.strftime('%H:%M:%S')}] lancement desk "
              f"(échecs précédents: {n}/{max_restarts})", flush=True)
        proc = subprocess.Popen([sys.executable, "-m", "aidesk", *extra],
                                cwd=str(ROOT),
                                env={**os.environ, "PYTHONUNBUFFERED": "1"})
        hang = False
        while proc.poll() is None:
            time.sleep(poll_s)
            if proc.poll() is not None:             # sorti pendant le sommeil
                break
            if desk_stale(_read_ts(state_p), time.time(), stale_s):
                hang = True
                print(f"[watchdog] tick figé (state.json > {stale_s:g}s) "
                      f"→ arrêt forcé du desk figé", flush=True)
                proc.terminate()
                try:
                    proc.wait(15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(10)
                break
        rc = proc.wait()
        if rc == 0 and not hang:
            print("[watchdog] sortie propre (KILL/--hours/Ctrl+C) → boucle terminée",
                  flush=True)
            return
        n += 1
        print(f"[watchdog] {'figeage' if hang else f'crash rc={rc}'} "
              f"→ relance dans {cooldown:g}s (l'état a été restauré au boot)",
              flush=True)
        time.sleep(cooldown)
    print("[watchdog] plafond d'échecs atteint → abandon (voir aide_watchdog)",
          flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("[watchdog] interrompu par l'opérateur", flush=True)
