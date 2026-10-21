from __future__ import annotations

"""Superviseur du desk : relance après crash tant que la sortie n'est pas propre.

Un code retour 0 (KILL, Ctrl+C propre, --hours fini) → arrêt de la boucle.
Un crash (exception) → redémarrage après cooldown, l'état étant restauré par le desk.

Usage : python3 tools/watchdog.py        (_variable AIDESK_MAX_RESTARTS pour plafonner)
"""

import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    max_restarts = int(os.getenv("AIDESK_MAX_RESTARTS", "50"))
    cooldown = float(os.getenv("AIDESK_WATCHDOG_COOLDOWN", "10"))
    # arguments passés au desk (ex : AIDESK_ARGS="--tick-seconds 60")
    extra = shlex.split(os.getenv("AIDESK_ARGS", ""))
    n = 0
    while n < max_restarts:
        print(f"[watchdog {time.strftime('%H:%M:%S')}] lancement desk "
              f"(échecs précédents: {n}/{max_restarts})", flush=True)
        rc = subprocess.call([sys.executable, "-m", "aidesk", *extra], cwd=str(ROOT),
                             env={**os.environ, "PYTHONUNBUFFERED": "1"})
        if rc == 0:
            print("[watchdog] sortie propre (KILL/--hours/Ctrl+C) → boucle terminée",
                  flush=True)
            return
        n += 1
        print(f"[watchdog] crash rc={rc} → relance dans {cooldown:g}s "
              f"(l'état a été restauré au boot)", flush=True)
        time.sleep(cooldown)
    print("[watchdog] plafond d'échecs atteint → abandon (voir aide_watchdog)", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("[watchdog] interrompu par l'opérateur", flush=True)
