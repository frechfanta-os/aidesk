from __future__ import annotations

"""Génère docs/data/*.json — données de la page spectateur (GitHub Pages).

Priorité aux API du dashboard en course (formateur d'events identique au live) ;
retombe sur les fichiers bruts si le dashboard est éteint.

Usage : python3 tools/build_site.py
Publié ensuite avec : git add docs/data && git commit -m "snapshot" && git push
"""

import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
BASE = "http://127.0.0.1:8787"


def _http(path: str, timeout: float = 4.0):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.load(r)


def get_state() -> dict:
    try:
        return _http("/api/state")
    except Exception:
        p = ROOT / "state.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def get_events() -> list[dict]:
    try:
        return _http("/api/events?n=70").get("events", [])
    except Exception:
        events: list[dict] = []
        p = ROOT / "events.jsonl"
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        events.append(json.loads(line))
                    except Exception:
                        continue
        return events[-70:]


def main() -> None:
    st = get_state()
    events = get_events()
    led = st.get("ledger", {})
    meta = {
        "snapshot_ts": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "events_kept": len(events),
        "net": round(led.get("wallet_usdt", 0) + led.get("mtm_usdt", 0), 2),
        "trades": len(st.get("trades_closed", [])),
    }
    out_dir = DOCS / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "state.json").write_text(
        json.dumps({**st, "snapshot_meta": meta}, indent=1), encoding="utf-8")
    (out_dir / "events.json").write_text(
        json.dumps({"events": events}, indent=1), encoding="utf-8")
    print(f"snapshot {meta['snapshot_ts']} | net {meta['net']} $ | "
          f"{meta['trades']} trade(s) | {len(events)} events")


if __name__ == "__main__":
    main()
