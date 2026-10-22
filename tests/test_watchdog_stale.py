"""Tests B7 — détection de figeage du desk par le watchdog (fonction pure).

Le desk peut être VIVANT (processus) mais FIGÉ (plus aucun tick écrit dans
state.json). desk_stale() décide sans jamais tuer sur le doute.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from tools.watchdog import desk_stale  # noqa: E402


def ts_utc(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_tick_fraiche_non_stale():
    now = datetime.now(timezone.utc).timestamp()
    fresh = ts_utc(datetime.fromtimestamp(now - 60, tz=timezone.utc))
    assert desk_stale(fresh, now, max_age=900) is False


def test_tick_vieux_est_stale():
    now = datetime.now(timezone.utc).timestamp()
    old = ts_utc(datetime.fromtimestamp(now - 1000, tz=timezone.utc))
    assert desk_stale(old, now, max_age=900) is True


def test_frontiere_juste_au_seuil():
    now = datetime.now(timezone.utc).timestamp()
    exact = ts_utc(datetime.fromtimestamp(now - 900.5, tz=timezone.utc))
    assert desk_stale(exact, now, 900) is True            # stale si > seuil
    assert desk_stale(ts_utc(datetime.fromtimestamp(now - 899, tz=timezone.utc)),
                      now, 900) is False


def test_ts_none_ou_corrompu_ne_tue_pas():
    now = time.time()
    assert desk_stale(None, now, 900) is False           # pas de kill sur le doute
    assert desk_stale("", now, 900) is False
    assert desk_stale(42, now, 900) is False             # type inattendu
    assert desk_stale("2026-06-31T99:00:00Z", now, 900) is False  # invalide
