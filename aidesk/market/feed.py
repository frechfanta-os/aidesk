from __future__ import annotations

import os
import random
import time
from typing import Any

import ccxt

from ..config import CORE_EXCHANGES, safe
from ..types import Features


class Feed:
    """Real market data (public endpoints, no keys) with offline fallback."""

    def __init__(self, exchange_env: str = "AIDESK_EXCHANGE",
                 fallbacks: list[str] | None = None, offline: bool = False) -> None:
        self.preferred = os.getenv(exchange_env, "binance").lower()
        self.fallbacks = fallbacks or CORE_EXCHANGES
        self.ex: ccxt.Exchange | None = None
        self.name: str | None = None
        self.offline = offline
        self.explicit = offline     # démo EXPLICITE (--offline) ≠ bascule réseau
        self._universe: list[str] = []
        self._last_price: dict[str, float] = {}
        self._offline_rng = random.Random(7)
        self._last_refresh = 0.0
        self._cached: dict[str, Features] = {}

    def connect(self) -> bool:
        if self.offline:
            return False
        order = [self.preferred] + [e for e in self.fallbacks if e != self.preferred]
        for ex_id in order:
            try:
                ex = getattr(ccxt, ex_id)({"enableRateLimit": True, "timeout": 15000})
                ex.load_markets()
                ex.fetch_ticker("BTC/USDT")
                self.ex, self.name = ex, ex_id
                return True
            except Exception:
                continue
        self.offline = True
        return False

    def symbols(self) -> list[str]:
        return self._universe or ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
                                  "XRP/USDT", "DOGE/USDT", "ADA/USDT", "LINK/USDT"]

    def refresh(self, top_n: int, min_interval: float = 60.0) -> dict[str, Features]:
        """One snapshot per refresh cycle; throttled to min_interval seconds."""
        now = time.time()
        if now - self._last_refresh < min_interval and self._cached:
            return self._cached
        # B7 : rétablissement — après une bascule réseau autonome (`ex` reste en
        # vie), re-tenter les VRAIS marchés à chaque cycle de rafraîchissement.
        # Une session démo explicite n'a pas de `ex` → reste en démo ; une fois
        # repassé live, le feed suit la voie normale.
        tickers = None
        if self.offline and self.ex is not None:
            try:
                tickers = self.ex.fetch_tickers()
                self.offline = False        # données réelles rétablies
            except Exception:
                self._last_refresh = now
                self._cached = self._offline_snapshot(top_n)
                return self._cached
        if self.offline or self.ex is None:
            self._last_refresh = now
            self._cached = self._offline_snapshot(top_n)
            return self._cached
        if tickers is None:
            try:
                tickers = self.ex.fetch_tickers()
            except Exception:
                try:
                    tickers = self.ex.fetch_tickers(self.symbols())
                except Exception:
                    self.offline = True
                    self._last_refresh = now
                    self._cached = self._offline_snapshot(top_n)
                    return self._cached
        rows: list[tuple[float, tuple[str, dict[str, Any]]]] = []
        for sym, t in tickers.items():
            if not (sym.endswith("/USDT") and ":" not in sym):
                continue
            qv = safe(t, "quoteVolume", 0.0) or 0.0
            if qv >= 1_000_000:
                rows.append((qv, (sym, t)))
        rows.sort(key=lambda x: -x[0])
        top = rows[:top_n]
        for _, (sym, t) in top:
            last = safe(t, "last") or safe(t, "close")
            if last:
                self._last_price[sym] = float(last)
        self._universe = [sym for _, (sym, _) in top]

        # Enrichissement OHLCV : TOUT le top (40 appels 15m ≈ 160 weight/min, très
        # sous les limites). Plafond optionnel via AIDESK_ENRICH_LIMIT.
        feats: dict[str, Features] = {}
        for _, (sym, t) in top:
            feats[sym] = self._basic_features(sym, t)
        enrich_limit = int(os.getenv("AIDESK_ENRICH_LIMIT", "0")) or len(feats)
        for f in list(feats.values())[:enrich_limit]:
            self._enrich(f)
        self._last_refresh = now
        self._cached = feats
        return feats

    def features_from_ticker(self, sym: str, t: dict[str, Any]) -> Features | None:
        """Public wrapper used to price positions that dropped out of the universe."""
        try:
            return self._basic_features(sym, t)
        except Exception:
            return None

    def _basic_features(self, sym: str, t: dict[str, Any]) -> Features:
        last = float(safe(t, "last") or safe(t, "close") or 0.0)
        qv = float(safe(t, "quoteVolume", 0.0) or 0.0)
        pct = float(safe(t, "percentage", 0.0) or 0.0)
        hi = float(safe(t, "high") or last or 1)
        lo = float(safe(t, "low") or last or 1)
        return Features(
            symbol=sym, last=last,
            bid=float(t["bid"]) if safe(t, "bid") else None,
            ask=float(t["ask"]) if safe(t, "ask") else None,
            quote_volume_24h=qv,
            mom_15m=0.0,           # enriched below when selected
            mom_1h=pct / 100.0,
            vol_surprise=1.0,
            range_pct=(hi - lo) / lo * 100 if lo else 0.0,
            ts=time.time(),        # fraîcheur : l'observation vient d'être reçue (B2)
        )

    def _enrich(self, f: Features) -> None:
        if not self.ex:
            return
        try:
            ohlcv = self.ex.fetch_ohlcv(f.symbol, "15m", limit=6)
            rows = [r for r in ohlcv if r[4] not in (None, 0)]
            if len(rows) >= 5:
                f.mom_15m = (f.last - float(rows[-2][4])) / float(rows[-2][4])
                f.mom_1h = (f.last - float(rows[-5][1])) / float(rows[-5][1])
                cvol = float(rows[-2][5]) * f.last
                f.vol_surprise = (cvol / (f.quote_volume_24h / 96.0)) if f.quote_volume_24h else 0.0
        except Exception:
            pass

    # ---------- offline fallback (random walk demo) ----------
    def _offline_snapshot(self, top_n: int) -> dict[str, Features]:
        now = time.time()
        syms = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
                "DOGE/USDT", "ADA/USDT", "LINK/USDT"][:max(6, min(top_n, 12))]
        base = {"BTC/USDT": 80000, "ETH/USDT": 4000, "SOL/USDT": 180,
                "BNB/USDT": 900, "XRP/USDT": 2.4, "DOGE/USDT": 0.22,
                "ADA/USDT": 1.0, "LINK/USDT": 20}
        out: dict[str, Features] = {}
        r = self._offline_rng
        for s in syms:
            drift = r.gauss(0, 0.004)
            if abs(drift) < 0.0012 and r.random() < 0.25:
                drift = r.choice([0.004, -0.004, 0.006])
            px = self._last_price.get(s, base.get(s, 100.0)) * (1 + drift)
            qv = 3e6 + r.random() * 50e6
            vol_surprise = 0.5 + r.random() * 2.8
            if r.random() < 0.15:
                vol_surprise *= 1.6
            self._last_price[s] = px
            out[s] = Features(symbol=s, last=px, bid=px * 0.9999, ask=px * 1.0001,
                              quote_volume_24h=qv, mom_15m=drift,
                              mom_1h=drift * r.uniform(1, 4),
                              vol_surprise=vol_surprise, range_pct=0.8 + r.random(),
                              ts=now)
        return out

    def last_ts(self) -> float:
        """Epoch du dernier rafraîchissement réussi (0.0 = jamais)."""
        return self._last_refresh
