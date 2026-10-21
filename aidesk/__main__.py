from __future__ import annotations

import argparse

from .config import Settings
from .runtime import Desk


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="aidesk",
        description="GHD AI Desk — trading multi-agents paper-first (données réelles).",
    )
    ap.add_argument("--hours", type=float, default=None,
                    help="durée du run en heures (défaut : continu)")
    ap.add_argument("--tick-seconds", type=float, default=60.0,
                    help="période du tick (défaut 60 s)")
    ap.add_argument("--quiet", action="store_true",
                    help="silencieux : uniquement le scoreboard final")
    ap.add_argument("--offline", action="store_true",
                    help="mode secours sans réseau (random walk de démo)")
    ap.add_argument("--db", default="aidesk.db", help="chemin SQLite")
    ap.add_argument("--config", default="desk.yaml", help="fichier de configuration")
    args = ap.parse_args()

    settings, matrix = Settings.load(args.config)
    desk = Desk(settings, matrix, offline=args.offline, db_path=args.db)
    try:
        desk.run(args.hours, args.tick_seconds, args.quiet)
    except KeyboardInterrupt:
        print("\nInterruption clavier — fermeture propre.")
        desk.stop = True
        desk._force_close_all("KBD-STOP")
        desk.final_report()


if __name__ == "__main__":
    main()
